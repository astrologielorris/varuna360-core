# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Edit Map Sub-tab - Interactive map for location selection

This sub-tab provides an interactive world map using cached OpenStreetMap tiles.
It works completely offline by reading from the SQLite tile cache.

Features:
- Click to select location
- Automatic timezone detection
- Reverse geocoding (city/country from coordinates)
- Capital quick-select dropdown
- Marker display
"""

import os
from typing import Optional, Tuple

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QFrame, QGroupBox, QGridLayout, QLineEdit
)
from PySide6.QtCore import Signal, Slot, Qt

# Theme imports
from ui.qt_theme import (
    BG, SURFACE, HOVER, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    BORDER, STATUS, ACCENTS, get_theme_colors, get_theme_accent, FONT_PRIMARY,
    scaled_area_px
)

# Default database path
DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "map_tiles_cache.db"
)

class EditMapSubTab(QWidget):
    """
    Interactive map sub-tab for location selection.

    Signals:
        location_selected(float, float, str, str): lat, lon, city, country
        apply_requested(): Emitted when Apply button clicked (switch to Edit Info)
    """

    location_selected = Signal(float, float, str, str)
    apply_requested = Signal()

    _shared_timezone_finder = None
    _shared_geolocator = None

    def __init__(self, parent_panel, show_apply_bar: bool = True):
        super().__init__()

        self.parent_panel = parent_panel
        self.detected_timezone = None
        self.current_lat = None
        self.current_lon = None
        self.current_city = ""
        self.current_country = ""
        self.show_apply_bar = show_apply_bar

        self._create_ui()
        self._connect_signals()

    def _create_ui(self):
        """Create the map UI with optional Apply button at bottom."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # === Search Bar (at top) ===
        self._create_search_bar(layout)

        # === Map Widget (takes most space) ===
        self._create_map_widget(layout)

        # === Apply Button Bar (optional) ===
        if self.show_apply_bar:
            self._create_apply_bar(layout)

        # Hidden labels for data storage (parent reads these)
        self.lat_label = QLabel("Lat: --")
        self.lat_label.hide()
        self.lon_label = QLabel("Lon: --")
        self.lon_label.hide()
        self.location_label = QLabel("")
        self.location_label.hide()
        self.timezone_label = QLabel("TZ: --")
        self.timezone_label.hide()
        self.zoom_label = QLabel("Zoom: 2")
        self.zoom_label.hide()

        # Dummy widgets for compatibility
        self.capital_combo = QComboBox()
        self.capital_combo.hide()

    def _create_search_bar(self, parent_layout):
        """Create a prominent location search bar at top of map."""
        from ui.qt_theme import get_theme_colors, is_light_theme
        theme = get_theme_colors()
        light = is_light_theme()

        bar_bg = theme['secondary'] if light else SURFACE
        bar_border = theme['secondary_light'] if light else BORDER
        input_bg = theme['secondary_dark'] if light else BG
        input_text = theme['secondary_text']

        search_frame = QFrame()
        search_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {bar_bg};
                border-bottom: 2px solid {theme['primary']};
                padding: 8px;
            }}
        """)
        search_layout = QHBoxLayout(search_frame)
        search_layout.setContentsMargins(12, 10, 12, 10)
        search_layout.setSpacing(10)

        # Search icon
        search_label = QLabel("🔍")
        search_label.setStyleSheet(f"color: {input_text}; font-size: {scaled_area_px('buttons')}px;")
        search_layout.addWidget(search_label)

        # Search entry (larger, more prominent)
        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("Type a city, country, or address to find it on the map...")
        self.search_entry.setMinimumWidth(250)
        self.search_entry.setStyleSheet(f"""
            QLineEdit {{
                background-color: {input_bg};
                color: {input_text};
                border: 2px solid {bar_border};
                border-radius: 6px;
                padding: 10px 14px;
                font-size: {scaled_area_px('buttons')}px;
                font-weight: 500;
            }}
            QLineEdit:focus {{
                border: 2px solid {theme['primary']};
            }}
        """)
        self.search_entry.returnPressed.connect(self._on_search)
        search_layout.addWidget(self.search_entry, stretch=1)

        # Search button (larger, matches input height)
        search_btn = QPushButton("Search")
        search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        search_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['primary']};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 24px;
                font-size: {scaled_area_px('buttons')}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {theme['primary_light']};
            }}
            QPushButton:pressed {{
                background-color: {theme['primary_dark']};
            }}
        """)
        search_btn.clicked.connect(self._on_search)
        search_layout.addWidget(search_btn)

        # Search status label (for feedback)
        self.search_status = QLabel("")
        self.search_status.setStyleSheet(f"color: {input_text}; font-size: {scaled_area_px('info_text')}px;")
        search_layout.addWidget(self.search_status)

        parent_layout.addWidget(search_frame)

    def _create_map_widget(self, parent_layout):
        """Create the map widget (offline or fallback)"""
        # Check if offline tiles exist
        if os.path.exists(DEFAULT_DB_PATH):
            try:
                from apps.widgets.offline_map_widget import OfflineMapWidget

                self.map_widget = OfflineMapWidget(DEFAULT_DB_PATH, self)
                self.map_widget.location_clicked.connect(self._on_map_clicked)
                self.has_map = True

                parent_layout.addWidget(self.map_widget, stretch=1)
                return
            except Exception as e:
                print(f"Failed to create offline map widget: {e}")

        # Fallback: No map available
        self.has_map = False
        self.map_widget = None

        fallback_frame = QFrame()
        fallback_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {BG};
                border: none;
            }}
        """)
        fallback_layout = QVBoxLayout(fallback_frame)
        fallback_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Warning message
        warning = QLabel(
            "📍 Map View Unavailable\n\n"
            "The offline map tile cache was not found.\n"
            "You can still enter coordinates manually below."
        )
        warning.setStyleSheet(f"""
            color: {TEXT_SECONDARY};
            font-size: {scaled_area_px('info_text')}px;
            padding: 40px;
        """)
        warning.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fallback_layout.addWidget(warning)

        # Manual coordinate entry
        manual_frame = QFrame()
        manual_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {SURFACE};
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 20px;
            }}
        """)
        manual_layout = QGridLayout(manual_frame)
        manual_layout.setSpacing(10)

        manual_layout.addWidget(QLabel("Latitude:"), 0, 0)
        self.manual_lat = QLineEdit()
        self.manual_lat.setPlaceholderText("e.g., 48.983333")
        self.manual_lat.setStyleSheet(f"""
            QLineEdit {{
                background-color: {BG};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                border-radius: 4px;
                padding: 8px;
            }}
        """)
        manual_layout.addWidget(self.manual_lat, 0, 1)

        manual_layout.addWidget(QLabel("Longitude:"), 1, 0)
        self.manual_lon = QLineEdit()
        self.manual_lon.setPlaceholderText("e.g., 2.266667")
        self.manual_lon.setStyleSheet(f"""
            QLineEdit {{
                background-color: {BG};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                border-radius: 4px;
                padding: 8px;
            }}
        """)
        manual_layout.addWidget(self.manual_lon, 1, 1)

        set_btn = QPushButton("Set Coordinates")
        set_btn.clicked.connect(self._on_manual_coordinates)
        accent = get_theme_accent()
        set_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {accent['base']};
                color: white;
                padding: 10px 20px;
                border: none;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {accent['hover']};
            }}
        """)
        manual_layout.addWidget(set_btn, 2, 0, 1, 2)

        fallback_layout.addWidget(manual_frame)
        fallback_layout.addStretch()

        parent_layout.addWidget(fallback_frame, stretch=1)

    def _create_apply_bar(self, parent_layout):
        """Create the Apply button bar at the bottom of the map view"""
        from ui.qt_theme import get_theme_colors, is_light_theme
        theme = get_theme_colors()
        light = is_light_theme()
        bar_bg = theme['secondary'] if light else SURFACE
        bar_border = theme['secondary_light'] if light else BORDER

        bar_frame = QFrame()
        bar_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {bar_bg};
                border-top: 1px solid {bar_border};
                padding: 8px;
            }}
        """)
        bar_layout = QHBoxLayout(bar_frame)
        bar_layout.setContentsMargins(12, 8, 12, 8)

        # Status label showing current selection
        self.selection_status = QLabel("Click on the map to select a location")
        self.selection_status.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_area_px('info_text')}px;")
        bar_layout.addWidget(self.selection_status)

        bar_layout.addStretch()

        # Apply button - use primary (accent) color
        self.apply_btn = QPushButton("✓ Apply && Return to Edit Info")
        self.apply_btn.setToolTip("Apply selected location and return to Edit Info tab")
        self.apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['primary']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 20px;
                font-size: {scaled_area_px('buttons')}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {theme['primary_light']};
            }}
            QPushButton:pressed {{
                background-color: {theme['primary_dark']};
            }}
            QPushButton:disabled {{
                background-color: {theme['secondary_dark']};
                color: {theme['secondary_text']};
            }}
        """)
        self.apply_btn.setEnabled(False)  # Disabled until location selected
        bar_layout.addWidget(self.apply_btn)

        parent_layout.addWidget(bar_frame)

    def _connect_signals(self):
        """Wire up signal connections"""
        if self.show_apply_bar and hasattr(self, 'apply_btn'):
            self.apply_btn.clicked.connect(self._apply_location_and_return)

    # =========================================================================
    # SHARED SINGLETONS (expensive to instantiate)
    # =========================================================================

    @classmethod
    def _get_timezone_finder(cls):
        """Lazy-init shared TimezoneFinder (loads ~50MB of shapefiles on first call)."""
        if cls._shared_timezone_finder is None:
            try:
                from timezonefinder import TimezoneFinder
                cls._shared_timezone_finder = TimezoneFinder()
            except ImportError:
                pass
        return cls._shared_timezone_finder

    @classmethod
    def _get_geolocator(cls):
        """Lazy-init shared Nominatim geocoder (reuses HTTP session)."""
        if cls._shared_geolocator is None:
            try:
                from geopy.geocoders import Nominatim
                cls._shared_geolocator = Nominatim(user_agent="Varuna360/1.0 (Vedic Astrology App; astrologielorris@gmail.com)", timeout=5)
            except ImportError:
                pass
        return cls._shared_geolocator

    # =========================================================================
    # EVENT HANDLERS
    # =========================================================================

    def _loading(self):
        """Get the app's loading manager, or None if unavailable."""
        gui = getattr(self.parent_panel, 'gui', None)
        return getattr(gui, 'loading_manager', None) if gui else None

    @Slot()
    def _on_search(self):
        """Handle location search using geocoding"""
        query = self.search_entry.text().strip()
        if not query:
            return

        self.search_status.setText("Searching...")
        theme = get_theme_colors()
        self.search_status.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_area_px('info_text')}px;")

        lm = self._loading()
        if lm:
            lm.start(f"Searching for '{query}'...")

        try:
            geolocator = self._get_geolocator()
            if geolocator is None:
                self.search_status.setText("geopy not installed")
                self.search_status.setStyleSheet(f"color: {STATUS['error']}; font-size: {scaled_area_px('info_text')}px;")
                return

            location = geolocator.geocode(query, language="en")
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()

            if location:
                lat = location.latitude
                lon = location.longitude

                # Get city/country from address
                city = ""
                country = ""
                if location.raw and 'address' in location.raw:
                    address = location.raw['address']
                    city = (address.get('city') or
                            address.get('town') or
                            address.get('village') or
                            address.get('municipality') or
                            address.get('state') or "")
                    country = address.get('country', '')
                else:
                    # Parse from display name
                    parts = location.address.split(", ")
                    if len(parts) >= 2:
                        city = parts[0]
                        country = parts[-1]

                # Set marker and center map
                if self.has_map and self.map_widget:
                    self.map_widget.set_marker(lat, lon)
                    self.map_widget.set_position(lat, lon)
                    self.map_widget.set_zoom(8)  # City level zoom

                # Trigger the click handler to update all displays
                self._on_map_clicked(lat, lon)

                # Update search status with found location
                self.search_status.setText(f"✓ Found: {location.address[:50]}...")
                self.search_status.setStyleSheet(f"color: {STATUS['success']}; font-size: {scaled_area_px('info_text')}px;")
            else:
                self.search_status.setText("❌ Location not found")
                self.search_status.setStyleSheet(f"color: {STATUS['error']}; font-size: {scaled_area_px('info_text')}px;")

        except Exception as e:
            self.search_status.setText(f"❌ Search failed: {str(e)[:30]}")
            self.search_status.setStyleSheet(f"color: {STATUS['error']}; font-size: {scaled_area_px('info_text')}px;")
        finally:
            if lm:
                lm.finish()

    @Slot(float, float)
    def _on_map_clicked(self, lat: float, lon: float):
        """Handle map click - auto-applies location immediately"""
        self.current_lat = lat
        self.current_lon = lon

        # Update coordinate display
        lat_dir = "N" if lat >= 0 else "S"
        lon_dir = "E" if lon >= 0 else "W"
        self.lat_label.setText(f"Lat: {abs(lat):.6f}° {lat_dir}")
        self.lon_label.setText(f"Lon: {abs(lon):.6f}° {lon_dir}")

        # Update zoom display
        if self.has_map and self.map_widget:
            self.zoom_label.setText(f"Zoom: {self.map_widget.get_zoom()}")

        lm = self._loading()
        if lm:
            lm.start("Resolving location...")

        try:
            # Reverse geocode and store as instance variables
            city, country = self._reverse_geocode(lat, lon)
            self.current_city = city
            self.current_country = country
            if city or country:
                location_text = f"{city}, {country}" if city and country else city or country
                self.location_label.setText(location_text)
            else:
                location_text = "Location selected"
                self.location_label.setText(location_text)

            # Update status and enable Apply button
            if hasattr(self, 'selection_status'):
                self.selection_status.setText(f"📍 {location_text} ({abs(lat):.4f}° {lat_dir}, {abs(lon):.4f}° {lon_dir})")
            if hasattr(self, 'apply_btn'):
                self.apply_btn.setEnabled(True)

            # Detect timezone
            self._detect_timezone(lat, lon)
        finally:
            if lm:
                lm.finish()

        # AUTO-APPLY: Emit signal immediately on map click
        self._apply_location()

    def _on_manual_coordinates(self):
        """Handle manual coordinate entry (fallback mode)"""
        try:
            lat = float(self.manual_lat.text())
            lon = float(self.manual_lon.text())

            if not (-90 <= lat <= 90):
                raise ValueError("Latitude must be -90 to 90")
            if not (-180 <= lon <= 180):
                raise ValueError("Longitude must be -180 to 180")

            self._on_map_clicked(lat, lon)
            self._apply_location()

        except ValueError as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Invalid Coordinates", str(e))

    @Slot()
    def _apply_location(self):
        """Apply selected location to the form"""
        if self.current_lat is None or self.current_lon is None:
            return

        # Use instance variables directly (set in _on_map_clicked)
        city = self.current_city
        country = self.current_country

        # Emit signal
        self.location_selected.emit(
            self.current_lat,
            self.current_lon,
            city,
            country
        )

    @Slot()
    def _apply_location_and_return(self):
        """Apply selected location and emit signal to return to Edit Info tab"""
        # First apply the location
        self._apply_location()

        # Then emit signal to switch back to Edit Info
        self.apply_requested.emit()

    # =========================================================================
    # UTILITIES
    # =========================================================================

    def _reverse_geocode(self, lat: float, lon: float) -> Tuple[str, str]:
        """Get city/country from coordinates"""
        city = ""
        country = ""

        try:
            geolocator = self._get_geolocator()
            if geolocator is not None:
                location = geolocator.reverse(f"{lat}, {lon}", language="en")
                from PySide6.QtWidgets import QApplication
                QApplication.processEvents()

                if location and location.raw:
                    address = location.raw.get('address', {})
                    city = (address.get('city') or
                            address.get('town') or
                            address.get('village') or
                            address.get('municipality') or "")
                    country = address.get('country', '')
                    return city, country
        except Exception:
            pass

        # Fallback: find nearest capital
        try:
            from tools.capitals_data import WORLD_CAPITALS

            best_dist = float('inf')
            best_capital = None

            for name, data in WORLD_CAPITALS.items():
                cap_lat = data.get('lat', 0)
                cap_lon = data.get('lon', 0)
                dist = (lat - cap_lat) ** 2 + (lon - cap_lon) ** 2

                if dist < best_dist:
                    best_dist = dist
                    best_capital = (name, data.get('country', ''))

            if best_capital:
                city, country = best_capital
        except ImportError:
            pass

        return city, country

    def _detect_timezone(self, lat: float, lon: float):
        """Auto-detect timezone from coordinates"""
        self.detected_timezone = None

        tf = self._get_timezone_finder()
        if tf is None:
            self.timezone_label.setText("TZ: (timezonefinder not installed)")
            return

        try:
            tz_name = tf.timezone_at(lat=lat, lng=lon)

            if tz_name:
                self.detected_timezone = tz_name

                try:
                    from datetime import datetime
                    import pytz
                    tz = pytz.timezone(tz_name)
                    now = datetime.now(tz)
                    offset = now.strftime('%z')
                    offset_formatted = f"{offset[:3]}:{offset[3:]}"
                    self.timezone_label.setText(f"TZ: {offset_formatted} ({tz_name})")
                except Exception:
                    self.timezone_label.setText(f"TZ: {tz_name}")
        except Exception:
            self.timezone_label.setText("TZ: --")

    def get_detected_timezone(self) -> Optional[str]:
        """Get the detected timezone name"""
        return self.detected_timezone

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def set_marker(self, lat: float, lon: float, city: str = "", country: str = ""):
        """Set marker position from external source"""
        self.current_lat = lat
        self.current_lon = lon
        if city:
            self.current_city = city
        if country:
            self.current_country = country

        # Update displays
        lat_dir = "N" if lat >= 0 else "S"
        lon_dir = "E" if lon >= 0 else "W"
        self.lat_label.setText(f"Lat: {abs(lat):.6f}° {lat_dir}")
        self.lon_label.setText(f"Lon: {abs(lon):.6f}° {lon_dir}")

        # Enable confirm button since we have a valid location
        if hasattr(self, 'apply_btn'):
            self.apply_btn.setEnabled(True)

        # Update map
        if self.has_map and self.map_widget:
            self.map_widget.set_marker(lat, lon)
            self.map_widget.set_position(lat, lon)

        # Detect timezone
        self._detect_timezone(lat, lon)

    # =========================================================================
    # THEME SUPPORT
    # =========================================================================

    def refresh_theme(self):
        """Update colors after theme change"""
        pass
