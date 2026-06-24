# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Dual Chart Widget - Reusable side-by-side + overlay chart display (PySide6)

Extracted from eclipse_panel.py Personal Eclipse page for reuse in:
- Eclipse Panel (Personal Eclipse comparison)
- Transit Panel (Natal + current transit)
- Any future chart comparison features

Supports:
- Left/right chart areas with configurable headers
- 3 view types: South Indian, Wheel, North Indian (F6 cycling)
- Overlay mode: right chart displayed as outer rim on wheel
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSplitter, QFrame, QStackedWidget, QSizePolicy
)
from PySide6.QtCore import Qt, Signal

# Chart view widgets
from apps.widgets.chart_view import SouthIndianView
from apps.widgets.wheel_view import WheelView
from apps.widgets.north_indian_view import NorthIndianView

# Theme imports
from ui.qt_theme import (
    BG, TEXT_PRIMARY, TEXT_SECONDARY, BORDER,
    get_theme_colors, get_frame_style, scaled_area_px
)

# Settings for background sync
from managers.settings_manager import get_settings


class DualChartWidget(QWidget):
    """
    Reusable widget for displaying two charts side-by-side with overlay mode.

    Features:
    - Left/right chart frames with customizable headers
    - 3 chart view types per side (South Indian, Wheel, North Indian)
    - Overlay mode in wheel view (right chart as outer rim)
    - Optional header widgets (dropdowns, controls) for each side

    Signals:
        overlay_toggled(bool): Emitted when overlay mode changes
        right_map_requested(): Emitted when map button on right side is clicked
    """

    overlay_toggled = Signal(bool)
    right_map_requested = Signal()  # For location selection popup

    def __init__(
        self,
        left_title: str = "Left Chart",
        right_title: str = "Right Chart",
        overlay_label: str = "Overlay",
        parent=None
    ):
        """
        Initialize the dual chart widget.

        Args:
            left_title: Header text for left chart (e.g., "Natal Chart")
            right_title: Header text for right chart (e.g., "Transit Chart")
            overlay_label: Label for overlay button
            parent: Parent widget
        """
        super().__init__(parent)

        self.left_title = left_title
        self.right_title = right_title
        self.overlay_label = overlay_label

        # Chart data storage
        self._left_chart = None
        self._right_chart = None
        self._left_varga_code = None
        self._right_varga_code = None
        self.aditya_mode = "aditya"
        self.use_western_names = False

        # View state (index: 0=South, 1=Wheel, 2=North)
        self.current_view_index = 0

        # Create UI
        self._create_ui()

    def _create_ui(self):
        """Create the dual chart UI layout."""
        theme = get_theme_colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # === HEADER with overlay button ===
        header_layout = QHBoxLayout()
        header_layout.addStretch()

        # Overlay toggle button (only visible in wheel view)
        self.overlay_btn = QPushButton(f"🔗 {self.overlay_label}")
        self.overlay_btn.setCheckable(True)
        self.overlay_btn.setChecked(False)
        self.overlay_btn.setVisible(False)  # Hidden until wheel view
        self.overlay_btn.setCursor(Qt.PointingHandCursor)
        self.overlay_btn.setToolTip("Show right chart as outer ring overlay (wheel view only)")
        self.overlay_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme["secondary"]};
                color: {theme["secondary_text"]};
                border: 1px solid {theme["secondary_light"]};
                border-radius: 4px;
                padding: 6px 12px;
                font-size: {scaled_area_px('buttons')}px;
            }}
            QPushButton:hover {{
                background-color: {theme["secondary_light"]};
            }}
            QPushButton:checked {{
                background-color: #FF8C00;
                color: white;
                border-color: #FF8C00;
            }}
        """)
        self.overlay_btn.clicked.connect(self._toggle_overlay_mode)
        header_layout.addWidget(self.overlay_btn)

        layout.addLayout(header_layout)

        # === CHARTS SECTION (QStackedWidget for mode switching) ===
        self.mode_stack = QStackedWidget()

        # --- Mode 0: Side-by-side view (default) ---
        self.charts_splitter = QSplitter(Qt.Horizontal)

        # Combo style for both sides — SPEC-THM-001 G11 live theme colors.
        self.combo_style = self._build_combo_style(theme)

        # --- LEFT chart ---
        left_frame = QFrame()
        left_frame.setStyleSheet(get_frame_style())
        left_layout = QVBoxLayout(left_frame)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(4)

        # Left header row
        self.left_header_row = QHBoxLayout()
        self.left_header_label = QLabel(f"👤 {self.left_title}")
        self.left_header_label.setStyleSheet(f"""
            font-size: {scaled_area_px('table_headers')}px;
            font-weight: bold;
            color: {theme["secondary_text"]};
        """)
        self.left_header_row.addWidget(self.left_header_label)
        self.left_header_row.addStretch()
        # Placeholder for custom header widget (e.g., dropdown)
        self.left_header_widget_slot = QHBoxLayout()
        self.left_header_row.addLayout(self.left_header_widget_slot)
        left_layout.addLayout(self.left_header_row)

        # Left chart info — SPEC-THM-001 G11 live theme colors.
        self.left_name_label = QLabel("No chart selected")
        self.left_name_label.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_area_px('tables')}px; font-weight: bold;")
        left_layout.addWidget(self.left_name_label)

        self.left_info_label = QLabel("")
        self.left_info_label.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_area_px('status')}px;")
        left_layout.addWidget(self.left_info_label)

        # Left chart view stack (3 view types)
        self.left_stack = QStackedWidget()
        self.left_stack.setMinimumSize(400, 400)
        self.left_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.left_south = SouthIndianView()
        self.left_wheel = WheelView()
        self.left_north = NorthIndianView()

        # Sync background with settings
        settings = get_settings()
        self.left_south.set_background(settings.get_background())

        self.left_stack.addWidget(self.left_south)   # Index 0
        self.left_stack.addWidget(self.left_wheel)   # Index 1
        self.left_stack.addWidget(self.left_north)   # Index 2

        left_layout.addWidget(self.left_stack, 1)
        self.charts_splitter.addWidget(left_frame)

        # --- RIGHT chart ---
        right_frame = QFrame()
        right_frame.setStyleSheet(get_frame_style())
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(4)

        # Right header row
        self.right_header_row = QHBoxLayout()
        self.right_header_label = QLabel(f"🌐 {self.right_title}")
        self.right_header_label.setStyleSheet(f"""
            font-size: {scaled_area_px('table_headers')}px;
            font-weight: bold;
            color: {theme["secondary_text"]};
        """)
        self.right_header_row.addWidget(self.right_header_label)
        self.right_header_row.addStretch()

        # Location button for map selection (same width as left dropdown for symmetry)
        self.right_map_btn = QPushButton("📍 Detecting location...")
        self.right_map_btn.setCursor(Qt.PointingHandCursor)
        self.right_map_btn.setToolTip("Click to change location for transit calculation")
        # SPEC-THM-001 G11 live theme colors for right_map_btn.
        self.right_map_btn.setStyleSheet(self._build_map_btn_style(theme))
        self.right_map_btn.clicked.connect(self._on_right_map_clicked)
        self.right_header_row.addWidget(self.right_map_btn)

        # Placeholder for custom header widget
        self.right_header_widget_slot = QHBoxLayout()
        self.right_header_row.addLayout(self.right_header_widget_slot)
        right_layout.addLayout(self.right_header_row)

        # Right chart info — SPEC-THM-001 G11 live theme colors.
        self.right_name_label = QLabel("No chart loaded")
        self.right_name_label.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_area_px('tables')}px; font-weight: bold;")
        right_layout.addWidget(self.right_name_label)

        self.right_info_label = QLabel("")
        self.right_info_label.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_area_px('status')}px;")
        right_layout.addWidget(self.right_info_label)

        # Right chart view stack (3 view types)
        self.right_stack = QStackedWidget()
        self.right_stack.setMinimumSize(400, 400)
        self.right_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.right_south = SouthIndianView()
        self.right_wheel = WheelView()
        self.right_north = NorthIndianView()

        # Sync background with settings
        self.right_south.set_background(settings.get_background())

        self.right_stack.addWidget(self.right_south)   # Index 0
        self.right_stack.addWidget(self.right_wheel)   # Index 1
        self.right_stack.addWidget(self.right_north)   # Index 2

        right_layout.addWidget(self.right_stack, 1)
        self.charts_splitter.addWidget(right_frame)

        # Force equal split with stretch factors
        self.charts_splitter.setStretchFactor(0, 1)  # Left gets equal stretch
        self.charts_splitter.setStretchFactor(1, 1)  # Right gets equal stretch
        self.charts_splitter.setSizes([500, 500])    # Initial equal sizes

        # Add splitter to mode stack
        self.mode_stack.addWidget(self.charts_splitter)  # Index 0

        # --- Mode 1: Overlay view (single wheel with outer rim) ---
        overlay_container = QFrame()
        overlay_container.setStyleSheet(get_frame_style())
        overlay_layout = QVBoxLayout(overlay_container)
        overlay_layout.setContentsMargins(8, 8, 8, 8)

        # Overlay header
        self.overlay_header = QLabel(f"{self.left_title} + {self.right_title} Overlay")
        self.overlay_header.setStyleSheet(f"""
            font-size: {scaled_area_px('table_headers')}px;
            font-weight: bold;
            color: {theme["secondary_text"]};
        """)
        self.overlay_header.setAlignment(Qt.AlignCenter)
        overlay_layout.addWidget(self.overlay_header)

        # Single large wheel for overlay
        self.overlay_wheel = WheelView()
        self.overlay_wheel.setMinimumSize(600, 600)
        self.overlay_wheel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        overlay_layout.addWidget(self.overlay_wheel, 1)

        self.mode_stack.addWidget(overlay_container)  # Index 1

        # Add mode stack to main layout
        layout.addWidget(self.mode_stack, 1)

    def set_left_header_widget(self, widget: QWidget):
        """
        Add a custom widget to the left chart header (e.g., dropdown).

        Args:
            widget: Widget to add (will be styled with combo_style if QComboBox)
        """
        # Clear existing widgets from slot
        while self.left_header_widget_slot.count():
            item = self.left_header_widget_slot.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        if widget:
            # Apply combo style if it's a QComboBox
            from PySide6.QtWidgets import QComboBox
            if isinstance(widget, QComboBox):
                widget.setStyleSheet(self.combo_style)
            self.left_header_widget_slot.addWidget(widget)

    def set_right_header_widget(self, widget: QWidget):
        """
        Add a custom widget to the right chart header (e.g., dropdown, refresh button).

        Args:
            widget: Widget to add
        """
        # Clear existing widgets from slot
        while self.right_header_widget_slot.count():
            item = self.right_header_widget_slot.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        if widget:
            from PySide6.QtWidgets import QComboBox
            if isinstance(widget, QComboBox):
                widget.setStyleSheet(self.combo_style)
            self.right_header_widget_slot.addWidget(widget)

    def update_from_chart(self, chart, side: str = "left", name: str = "", info: str = "",
                           use_western_names: bool = False, varga_code=None, aditya_mode=None):
        """Set data for one side from a libaditya Chart (Chart-Everywhere Issue 6d)."""
        from libaditya.objects.context import Circle
        if aditya_mode is None:
            aditya_mode = "aditya" if chart.context.circle == Circle.ADITYA else "tropical_classic"

        if side == "left":
            self._left_chart = chart
            self._left_varga_code = varga_code
            self.aditya_mode = aditya_mode
            self.use_western_names = use_western_names
            self.left_name_label.setText(name if name else "Chart loaded")
            self.left_info_label.setText(info if info else "")
            self.left_south.update_from_chart(chart, varga_code=varga_code, use_western_names=use_western_names, aditya_mode=aditya_mode)
            self.left_wheel.update_from_chart(chart, varga_code=varga_code, use_western_names=use_western_names, aditya_mode=aditya_mode)
            self.left_north.update_from_chart(chart, varga_code=varga_code, use_western_names=use_western_names, aditya_mode=aditya_mode)
        else:
            self._right_chart = chart
            self._right_varga_code = varga_code
            self.right_name_label.setText(name if name else "Chart loaded")
            self.right_info_label.setText(info if info else "")
            self.right_south.update_from_chart(chart, varga_code=varga_code, use_western_names=use_western_names, aditya_mode=aditya_mode)
            self.right_wheel.update_from_chart(chart, varga_code=varga_code, use_western_names=use_western_names, aditya_mode=aditya_mode)
            self.right_north.update_from_chart(chart, varga_code=varga_code, use_western_names=use_western_names, aditya_mode=aditya_mode)

        if self.mode_stack.currentIndex() == 1:
            self._update_overlay()

    def clear_side(self, side: str = "left", name: str = "", info: str = ""):
        """Clear one side, resetting Chart state and child view rendering."""
        if side == "left":
            self._left_chart = None
            self._left_varga_code = None
            self.left_name_label.setText(name if name else "")
            self.left_info_label.setText(info if info else "")
            self.left_south.scene.clear()
            self.left_wheel.clear_chart()
            self.left_north.clear_chart()
        else:
            self._right_chart = None
            self._right_varga_code = None
            self.right_name_label.setText(name if name else "")
            self.right_info_label.setText(info if info else "")
            self.right_south.scene.clear()
            self.right_wheel.clear_chart()
            self.right_north.clear_chart()

        if self.mode_stack.currentIndex() == 1:
            self._update_overlay()

    def sync_chart_view(self, view_name: str):
        """
        Sync chart view type with main app (F6 cycling support).

        Args:
            view_name: "south_indian", "wheel", or "north_indian"
        """
        view_map = {
            "south_indian": 0,
            "wheel": 1,
            "north_indian": 2
        }
        index = view_map.get(view_name, 0)
        self.current_view_index = index

        # Update both chart stacks
        self.left_stack.setCurrentIndex(index)
        self.right_stack.setCurrentIndex(index)

        # Show overlay button only in wheel view
        is_wheel = (view_name == "wheel")
        self.overlay_btn.setVisible(is_wheel)

        # If leaving wheel view, disable overlay mode
        if not is_wheel and self.overlay_btn.isChecked():
            self.overlay_btn.setChecked(False)
            self._toggle_overlay_mode()  # Reset to side-by-side


    def set_overlay_mode(self, enabled: bool):
        """
        Programmatically set overlay mode.

        Args:
            enabled: True for overlay mode, False for side-by-side
        """
        if self.overlay_btn.isChecked() != enabled:
            self.overlay_btn.setChecked(enabled)
            self._toggle_overlay_mode()

    def is_overlay_mode(self) -> bool:
        """Check if currently in overlay mode."""
        return self.mode_stack.currentIndex() == 1

    def _toggle_overlay_mode(self):
        """Toggle between side-by-side and overlay modes."""
        is_overlay = self.overlay_btn.isChecked()

        if is_overlay:
            # Switch to overlay mode
            self.mode_stack.setCurrentIndex(1)
            self._update_overlay()
        else:
            # Switch to side-by-side mode
            self.mode_stack.setCurrentIndex(0)

        self.overlay_toggled.emit(is_overlay)

    def _on_right_map_clicked(self):
        """Handle map button click on right chart - emit signal for location selection."""
        self.right_map_requested.emit()

    def set_right_location_text(self, location_name: str):
        """
        Update the location button text on the right chart.

        Args:
            location_name: Location name to display (e.g., "Saint-Denis, RE")
        """
        self.right_map_btn.setText(f"📍 {location_name}")
        self.right_map_btn.setToolTip(f"Current: {location_name}\nClick to change location")

    def _update_overlay(self):
        """Update the overlay wheel with current chart data."""
        left = getattr(self, '_left_chart', None)
        right = getattr(self, '_right_chart', None)

        if left:
            varga_code = getattr(self, '_left_varga_code', None)
            aditya_mode = getattr(self, 'aditya_mode', None)
            self.overlay_wheel.update_from_chart(left, varga_code=varga_code, use_western_names=self.use_western_names, aditya_mode=aditya_mode)

        if right:
            right_varga = getattr(self, '_right_varga_code', None)
            self.overlay_wheel.update_outer_rim_from_chart(right, varga_code=right_varga)
        else:
            self.overlay_wheel.set_outer_rim_data(None)

        left_name = self.left_name_label.text()
        right_name = self.right_name_label.text()
        self.overlay_header.setText(f"\U0001f464 {left_name} + \U0001f310 {right_name}")

        self.overlay_wheel.draw_wheel()

    def _build_combo_style(self, theme):
        """Combo style using live theme colors (SPEC-THM-001 G11)."""
        return f"""
            QComboBox {{
                background-color: {theme["secondary_dark"]};
                color: {theme["secondary_text"]};
                border: 1px solid {theme["secondary_light"]};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: {scaled_area_px('buttons')}px;
                min-width: 200px;
            }}
            QComboBox:hover {{
                border-color: {theme["primary"]};
            }}
            QComboBox::drop-down {{
                border: none;
                padding-right: 8px;
            }}
        """

    def _build_map_btn_style(self, theme):
        """Map button style using live theme colors (SPEC-THM-001 G11)."""
        return f"""
            QPushButton {{
                background-color: {theme["secondary_dark"]};
                color: {theme["secondary_text"]};
                border: 1px solid {theme["secondary_light"]};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: {scaled_area_px('buttons')}px;
                min-width: 200px;
                text-align: left;
            }}
            QPushButton:hover {{
                border-color: {theme["primary"]};
            }}
        """

    def refresh_theme(self):
        """Refresh theme colors after theme change.

        SPEC-THM-001 G10/G11: expanded to cover all previously-missed widgets
        (name labels, info labels, map button, combos via stored style).
        """
        theme = get_theme_colors()

        # Update header labels
        self.left_header_label.setStyleSheet(f"""
            font-size: {scaled_area_px('table_headers')}px;
            font-weight: bold;
            color: {theme["secondary_text"]};
        """)
        self.right_header_label.setStyleSheet(f"""
            font-size: {scaled_area_px('table_headers')}px;
            font-weight: bold;
            color: {theme["secondary_text"]};
        """)
        if hasattr(self, 'overlay_header'):
            self.overlay_header.setStyleSheet(f"""
                font-size: {scaled_area_px('table_headers')}px;
                font-weight: bold;
                color: {theme["secondary_text"]};
            """)

        # Update overlay button
        self.overlay_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme["secondary"]};
                color: {theme["secondary_text"]};
                border: 1px solid {theme["secondary_light"]};
                border-radius: 4px;
                padding: 6px 12px;
                font-size: {scaled_area_px('buttons')}px;
            }}
            QPushButton:hover {{
                background-color: {theme["secondary_light"]};
            }}
            QPushButton:checked {{
                background-color: #FF8C00;
                color: white;
                border-color: #FF8C00;
            }}
        """)

        # SPEC-THM-001 G11: name/info labels and map button were missing.
        if hasattr(self, 'left_name_label'):
            self.left_name_label.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_area_px('tables')}px; font-weight: bold;")
        if hasattr(self, 'left_info_label'):
            self.left_info_label.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_area_px('status')}px;")
        if hasattr(self, 'right_name_label'):
            self.right_name_label.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_area_px('tables')}px; font-weight: bold;")
        if hasattr(self, 'right_info_label'):
            self.right_info_label.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_area_px('status')}px;")
        if hasattr(self, 'right_map_btn'):
            self.right_map_btn.setStyleSheet(self._build_map_btn_style(theme))

        # Rebuild combo style and re-apply to any combos that were added via
        # the header slot (so newly added or theme-changed combos pick up colors).
        self.combo_style = self._build_combo_style(theme)
        for slot_attr in ('left_header_widget_slot', 'right_header_widget_slot'):
            slot = getattr(self, slot_attr, None)
            if slot is None:
                continue
            for i in range(slot.count()):
                item = slot.itemAt(i)
                if item is None:
                    continue
                w = item.widget()
                if w is not None and w.__class__.__name__ == 'QComboBox':
                    w.setStyleSheet(self.combo_style)

        # SPEC-THM-001 G10: propagate to the embedded SouthIndian/Wheel/NorthIndian
        # views so their backgrounds and text recolor too.
        for view_attr in ('left_south', 'left_wheel', 'left_north',
                          'right_south', 'right_wheel', 'right_north',
                          'overlay_wheel'):
            v = getattr(self, view_attr, None)
            if v is not None and hasattr(v, 'refresh_theme'):
                v.refresh_theme()

    def get_left_wheel(self) -> WheelView:
        """Get the left wheel view for direct access if needed."""
        return self.left_wheel

    def get_right_wheel(self) -> WheelView:
        """Get the right wheel view for direct access if needed."""
        return self.right_wheel

    def get_overlay_wheel(self) -> WheelView:
        """Get the overlay wheel view for direct access if needed."""
        return self.overlay_wheel
