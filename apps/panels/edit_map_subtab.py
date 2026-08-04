# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
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
from ui.themed_style import ThemedStyleMixin

# Default database path
DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "map_tiles_cache.db"
)

#: Zoom a successful search lands on (SPEC-MAP-001 D-10).
#: This MUST stay at the cached ceiling. It was 8 — one level past the last
#: cached level — which made every visible tile a serial network fetch on the
#: GUI thread and is the whole reason a search froze the app for 10-20 s.
from apps.widgets.map_tiles import SOFT_MAX_ZOOM as MAP_SEARCH_ZOOM

class EditMapSubTab(ThemedStyleMixin, QWidget):
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

        # SPEC-MAP-001 §4.5: start the 788 ms TimezoneFinder construction NOW,
        # in the background, so it is finished long before the user's first
        # click instead of being paid inside it.
        try:
            from core.tz_finder import start_warmup
            start_warmup()
        except Exception:
            pass

        # Off-GUI-thread geocoding with a generation guard (INV-1, INV-8).
        from core.geocode_service import GeocodeWorker
        self._search_worker = GeocodeWorker(self)
        self._search_worker.resolved.connect(self._on_search_resolved)
        self._name_worker = GeocodeWorker(self)
        self._name_worker.resolved.connect(self._on_name_resolved)

        # ONE selection generation shared by every async applier. Each worker's
        # own counter only protects it from ITSELF; it cannot see that a
        # different input has since changed the selection. Without this, a slow
        # search for Paris landing after the user clicked Tokyo moved the
        # marker back and reapplied Paris's coordinates and timezone.
        self._sel_gen = 0
        self._search_gen = -1
        self._name_gen = -1

        # SPEC-MAP-002. Set by _create_map_widget when a real map exists; the
        # fallback (no tile cache) path leaves them None and every use site
        # guards, so a machine without tiles keeps working exactly as before.
        self.info_card = None
        self.asc_controller = None

        self._create_ui()
        self._connect_signals()

    # =========================================================================
    # ASCENDANT PREVIEW (SPEC-MAP-002)
    # =========================================================================

    def set_time_basis(self, local_fields, mode: str = None,
                       ayanamsa: int = None, sign_names=None,
                       utc_input: bool = False):
        """Give the picker the chart it is picking a place FOR.

        `local_fields` is {year, month, day, hour, minute, second} of the birth
        CIVIL time. Pass None to switch the feature off — hosts with no single
        birth instant (Birth Finder, Lunar New Year, the Eclipse panel) simply
        never call this, and INV-4 holds by construction.
        """
        if self.asc_controller is None:
            return
        self.asc_controller.set_time_basis(local_fields, mode, ayanamsa,
                                           sign_names, utc_input=utc_input)
        available = self.asc_controller.has_time_basis()
        if hasattr(self, "asc_btn"):
            self.asc_btn.setVisible(available)
            if not available:
                self.asc_btn.setChecked(False)
        if available and self.current_lat is not None:
            self._refresh_card_ascendant()

    @Slot(bool)
    def _on_asc_toggled(self, checked: bool):
        if self.asc_controller is None:
            return
        self.asc_controller.set_bands_enabled(checked)

    @Slot(float, float)
    def _on_map_hovered(self, lat: float, lon: float):
        """Live readout. Already throttled to 60 ms by the map widget."""
        if self.asc_controller is None or self.info_card is None:
            return
        if not self.asc_controller.has_time_basis():
            return

        # Hovering ON the selection must keep showing the selection's name.
        # Without this the card flipped to a generic "Point" the instant the
        # pointer settled after a click — which it always does, because you
        # click with the pointer over the map.
        if self._is_near_selection(lat, lon):
            self._refresh_card_ascendant()
            return

        self.info_card.set_place("Point", "")
        self.info_card.set_coordinates(lat, lon)
        self.asc_controller.apply_readout_to_card(lat, lon)
        self.info_card.show()
        self.info_card.reposition()

    def _is_near_selection(self, lat: float, lon: float) -> bool:
        """Within a pin's width of the current selection.

        Degrees, not pixels: the tolerance has to mean the same thing whatever
        the zoom, and at the zooms this picker allows a quarter degree is never
        more than a pin-head away from where the user actually clicked.
        """
        if self.current_lat is None or self.current_lon is None:
            return False
        return (abs(lat - self.current_lat) < 0.25
                and abs(lon - self.current_lon) < 0.25)

    @Slot()
    def _on_map_hover_left(self):
        """Back to the selection — the card must not keep showing a stray point."""
        if self.current_lat is None:
            if self.info_card is not None:
                self.info_card.hide()
            return
        self._refresh_card_ascendant()

    def _refresh_card_ascendant(self):
        """Repaint the card from the CURRENT SELECTION."""
        if self.info_card is None or self.current_lat is None:
            return
        self.info_card.set_place(self.current_city, self.current_country)
        self.info_card.set_coordinates(self.current_lat, self.current_lon)
        if self.detected_timezone:
            offset = ""
            if self.asc_controller is not None:
                offset = self.asc_controller._offset_string(
                    self.detected_timezone)
            self.info_card.set_timezone(self.detected_timezone, offset)
        if self.asc_controller is not None:
            self.asc_controller.apply_readout_to_card(
                self.current_lat, self.current_lon)
        self.info_card.show()
        self.info_card.reposition()

    def eventFilter(self, obj, event):
        """Keep the card in the corner when the viewport resizes."""
        from PySide6.QtCore import QEvent
        if (self.info_card is not None and self.map_widget is not None
                and obj is self.map_widget.viewport()
                and event.type() == QEvent.Type.Resize):
            self.info_card.reposition()
        return super().eventFilter(obj, event)

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
        """Create a prominent location search bar at top of map.

        td-iqjb.7 (Wave G): every themed widget here is registered via
        ThemedStyleMixin so a LIVE theme switch re-applies it. Before, this bar
        was styled ONCE at construction from an is_light_theme() branch and
        refresh_theme() was a bare `pass` -> black search strip + pale chips
        survived a switch. Each style_fn re-runs the light/dark branch inside
        itself (see _map_bar_colors), so replay re-decides polarity each call.
        """
        # search_frame stored on self so the visual harness can region-sample
        # this exact strip (page-mean sampling proved insensitive to thin bars).
        self.search_frame = self._register_themed(QFrame(), self._search_frame_style)
        search_layout = QHBoxLayout(self.search_frame)
        search_layout.setContentsMargins(12, 10, 12, 10)
        search_layout.setSpacing(10)

        # Search icon
        search_label = self._register_themed(QLabel("🔍"), self._search_label_style)
        search_layout.addWidget(search_label)

        # Search entry (larger, more prominent)
        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("Type a city, country, or address to find it on the map...")
        self.search_entry.setMinimumWidth(250)
        self._register_themed(self.search_entry, self._search_entry_style)
        self.search_entry.returnPressed.connect(self._on_search)
        search_layout.addWidget(self.search_entry, stretch=1)

        # Search button (larger, matches input height)
        search_btn = QPushButton("Search")
        search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._register_themed(search_btn, self._search_btn_style)
        search_btn.clicked.connect(self._on_search)
        search_layout.addWidget(search_btn)

        # Ascendant band toggle (SPEC-MAP-002 D-7). It lives on THIS bar on
        # purpose: a dedicated control row is forbidden, and the search bar has
        # spare width at every window size.
        self.asc_btn = QPushButton("Ascendant")
        self.asc_btn.setCheckable(True)
        self.asc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.asc_btn.setToolTip(
            "Show where each sign rises for this chart's moment.\n"
            "The bands are drawn for one instant; the card's Ascendant "
            "follows the place you point at.")
        self._register_themed(self.asc_btn, self._asc_btn_style)
        self.asc_btn.toggled.connect(self._on_asc_toggled)
        self.asc_btn.setVisible(False)      # until a host supplies a time basis
        search_layout.addWidget(self.asc_btn)

        # Search status label (for feedback). Registered with the neutral style;
        # _on_search still overrides it live with success/error colors (a later
        # theme switch harmlessly resets it to neutral).
        self.search_status = QLabel("")
        self._register_themed(self.search_status, self._search_status_style)
        search_layout.addWidget(self.search_status)

        parent_layout.addWidget(self.search_frame)

    def _create_map_widget(self, parent_layout):
        """Create the map widget (offline or fallback)"""
        # Check if offline tiles exist
        if os.path.exists(DEFAULT_DB_PATH):
            try:
                from apps.widgets.offline_map_widget import OfflineMapWidget

                self.map_widget = OfflineMapWidget(DEFAULT_DB_PATH, self)
                self.map_widget.location_clicked.connect(self._on_map_clicked)
                # Quiet inline hint at the offline detent — never a modal.
                self.map_widget.detent_reached.connect(self._on_detent_reached)
                self.map_widget.hovered.connect(self._on_map_hovered)
                self.map_widget.hover_left.connect(self._on_map_hover_left)
                self.map_widget.set_graticule_visible(True)
                self.has_map = True

                # SPEC-MAP-002 §4.4: the card is a child of the VIEWPORT, so it
                # stays pinned to the corner while the map pans under it.
                from apps.widgets.map_info_card import MapInfoCard
                from apps.widgets.map_ascendant_controller import (
                    MapAscendantController,
                )
                self.info_card = MapInfoCard(self.map_widget.viewport())
                # Force the first layout and stylesheet parse NOW, while the
                # card is hidden. Left until the first click it costs ~58 ms
                # inside that click — the exact shape of stall SPEC-MAP-001
                # spent itself removing, just moved to a new widget.
                self.info_card.set_place("Sample", "Sample")
                self.info_card.set_coordinates(0.0, 0.0)
                self.info_card.set_ascendant("Ascendant  00°00'  Sample")
                self.info_card.adjustSize()
                self.info_card.set_place("", "")
                self.info_card.set_ascendant("")
                self.asc_controller = MapAscendantController(
                    self.map_widget, self.info_card, parent=self)
                self.map_widget.viewport().installEventFilter(self)

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
        """Create the Apply button bar at the bottom of the map view.

        td-iqjb.7 (Wave G): registered for live re-theme (was construction-only).
        """
        self.apply_bar_frame = self._register_themed(QFrame(), self._apply_bar_frame_style)
        bar_layout = QHBoxLayout(self.apply_bar_frame)
        bar_layout.setContentsMargins(12, 8, 12, 8)

        # Status label showing current selection
        self.selection_status = QLabel("Click on the map to select a location")
        self._register_themed(self.selection_status, self._selection_status_style)
        bar_layout.addWidget(self.selection_status)

        bar_layout.addStretch()

        # Apply button - use primary (accent) color
        self.apply_btn = QPushButton("✓ Apply && Return to Edit Info")
        self.apply_btn.setToolTip("Apply selected location and return to Edit Info tab")
        self.apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._register_themed(self.apply_btn, self._apply_btn_style)
        self.apply_btn.setEnabled(False)  # Disabled until location selected
        bar_layout.addWidget(self.apply_btn)

        parent_layout.addWidget(self.apply_bar_frame)

    def _connect_signals(self):
        """Wire up signal connections"""
        if self.show_apply_bar and hasattr(self, 'apply_btn'):
            self.apply_btn.clicked.connect(self._apply_location_and_return)

    # =========================================================================
    # SHARED SINGLETONS (expensive to instantiate)
    # =========================================================================

    @classmethod
    def _get_timezone_finder(cls):
        """The ONE process-wide TimezoneFinder (SPEC-MAP-001 INV-7).

        Was a per-class cache here and a fresh 788 ms construction in two other
        modules; `core.tz_finder` now owns the single instance and warms it in
        the background when this sub-tab is created.
        """
        from core.tz_finder import get_timezone_finder
        return get_timezone_finder()

    @classmethod
    def _get_geolocator(cls):
        """Retained for callers outside this class.

        Nothing in this file should reach for it: geocoding goes through
        `core.geocode_service`, which adds the local tier, the persistent
        cache, and the off-thread execution this class needs (INV-1).
        """
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

    def _status(self, text: str, color: str = None):
        theme = get_theme_colors()
        self.search_status.setText(text)
        self.search_status.setStyleSheet(
            f"color: {color or theme['secondary_text']}; "
            f"font-size: {scaled_area_px('info_text')}px;")

    @Slot()
    def _on_search(self):
        """Search for a place. Returns immediately; the map stays alive.

        SPEC-MAP-001 §4.5 / D-9, D-10. What this used to be, and why it froze
        for 10-20 s: a synchronous Nominatim call on the GUI thread behind a
        modal overlay, followed by `set_zoom(8)` — a level with ZERO cached
        tiles, so every visible tile then went to the network one at a time
        with a 5 s timeout each. Now the lookup runs on a worker and the map
        lands on SOFT_MAX (7), which is fully cached and therefore instant.
        """
        query = self.search_entry.text().strip()
        if not query:
            return

        self._status("Searching...")
        # No loading_manager here: a modal overlay was the visible symptom of a
        # blocking call, and there is no longer a blocking call to cover.
        self._search_gen = self._bump_selection()
        self._search_worker.request_forward(query)

    def _bump_selection(self) -> int:
        """Invalidate every async result that has not landed yet.

        Called by search, click and set_marker alike, so whichever input the
        user made LAST wins regardless of which network reply is slowest.
        """
        self._sel_gen += 1
        return self._sel_gen

    @Slot(object)
    def _on_search_resolved(self, result):
        """Worker came back. Drop it if the user has since picked elsewhere."""
        if self._search_gen != self._sel_gen:
            return                      # a click or another search superseded it
        if result is None:
            self._status("❌ Location not found", STATUS['error'])
            return

        if self.has_map and self.map_widget:
            self.map_widget.set_marker(result.lat, result.lon)
            self.map_widget.set_position(result.lat, result.lon)
            # D-10: the cached ceiling, not 8. This one line is the difference
            # between instant and a ~50-tile serial network storm.
            self.map_widget.set_zoom(MAP_SEARCH_ZOOM)

        self._apply_selection(result.lat, result.lon,
                              city=result.city, country=result.country,
                              resolve_name=not (result.city or result.country))

        label = result.label or f"{result.lat:.4f}, {result.lon:.4f}"
        self._status(f"✓ Found: {label[:50]}", STATUS['success'])

    @Slot()
    def _on_detent_reached(self):
        """Wheel zoom hit the offline boundary (INV-4). Inline hint only."""
        self._status("Zoom limit — scroll again to load detailed tiles online")

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

        self._apply_selection(lat, lon, resolve_name=True)

    def _apply_selection(self, lat: float, lon: float, city: str = "",
                         country: str = "", resolve_name: bool = True):
        """Commit a picked location. Returns in well under 100 ms.

        SPEC-MAP-001 INV-3, the ordering that matters:

          1. lat/lon and the IANA timezone are resolved LOCALLY and applied
             synchronously, so `location_selected` carries everything that can
             affect a chart. The timezone lookup is 0.7 ms once the finder is
             warm (warm-up starts when this sub-tab is built).
          2. The nearest capital is shown at once as a placeholder name.
          3. The real place NAME is fetched on a worker and patches the label
             later. It is cosmetic and must never touch lat/lon/tz.

        Previously steps 1-3 were one synchronous block behind a modal overlay:
        a Nominatim round trip plus a 788 ms TimezoneFinder construction, which
        is the ~2 s every click cost.
        """
        lat_dir = "N" if lat >= 0 else "S"
        lon_dir = "E" if lon >= 0 else "W"

        # This pick is now the truth. Anything still in flight for an older
        # pick — a slow search, an older reverse geocode — is dead.
        gen = self._bump_selection()

        self.current_lat = lat
        self.current_lon = lon

        # --- 1. timezone: local, synchronous, chart-affecting --------------
        self._detect_timezone(lat, lon)

        # --- 2. an instant name -------------------------------------------
        if not (city or country):
            city, country = self._nearest_capital(lat, lon)
        self.current_city = city
        self.current_country = country
        self._show_selection(lat, lon, lat_dir, lon_dir)
        if self.map_widget is not None:
            # Position AND label together. A real click already moved the pin in
            # mouseReleaseEvent, but a PROGRAMMATIC selection (remote control,
            # a search result, the host restoring a chart) never goes through
            # it — so setting only the label left the pin on the previous
            # location wearing the new place's name. The real-screen capture
            # showed a pin over the United States labelled PARIS.
            # Same coordinates re-applied is a no-op: set_marker only pulses
            # when the point actually moved.
            self.map_widget.set_marker(lat, lon, label=city or country or "")

        if hasattr(self, 'apply_btn'):
            self.apply_btn.setEnabled(True)

        # --- 2b. the card, and the bands' instant (SPEC-MAP-002) -----------
        # Moving the selection moves its timezone, which moves the UTC instant
        # the bands belong to, so the scan is re-requested. It runs on a worker
        # and its result is generation-guarded, so this costs nothing here.
        self._refresh_card_ascendant()
        if self.asc_controller is not None:
            self.asc_controller.request_bands(lat, lon)

        # --- 3. the real name, asynchronously (INV-8 guards staleness) -----
        if resolve_name:
            self._name_gen = gen
            self._name_worker.request_reverse(lat, lon)
        else:
            self._name_gen = -1
            self._name_worker.cancel()

        # AUTO-APPLY: coordinates + timezone are already final.
        self._apply_location()

    def _show_selection(self, lat, lon, lat_dir, lon_dir):
        city, country = self.current_city, self.current_country
        if city or country:
            text = f"{city}, {country}" if city and country else city or country
        else:
            text = "Location selected"
        self.location_label.setText(text)
        if hasattr(self, 'selection_status'):
            self.selection_status.setText(
                f"📍 {text} ({abs(lat):.4f}° {lat_dir}, {abs(lon):.4f}° {lon_dir})")

    @Slot(object)
    def _on_name_resolved(self, result):
        """A reverse geocode landed. Label only — never the coordinates."""
        if self._name_gen != self._sel_gen:
            return                      # names a location the user left
        if result is None or self.current_lat is None:
            return
        if not (result.city or result.country):
            return
        self.current_city = result.city or self.current_city
        self.current_country = result.country or self.current_country

        lat, lon = self.current_lat, self.current_lon
        self._show_selection(lat, lon,
                             "N" if lat >= 0 else "S", "E" if lon >= 0 else "W")
        # Re-emit so the form picks up the better name. Coordinates and the
        # timezone are byte-identical to what step 1 already applied.
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

    @staticmethod
    def _nearest_capital(lat: float, lon: float) -> Tuple[str, str]:
        """Closest known capital. Offline, instant, no network (INV-1).

        Shown the moment the user clicks, so the selection always has a name
        even before the real reverse geocode lands.
        """
        try:
            from tools.capitals_data import WORLD_CAPITALS
        except ImportError:
            return "", ""

        best, best_dist = None, float('inf')
        for name, data in WORLD_CAPITALS.items():
            dist = ((lat - data.get('lat', 0)) ** 2
                    + (lon - data.get('lon', 0)) ** 2)
            if dist < best_dist:
                best_dist = dist
                best = (name, data.get('country', ''))
        return best if best else ("", "")

    def _reverse_geocode(self, lat: float, lon: float) -> Tuple[str, str]:
        """Deprecated: kept only so external callers do not break.

        This used to run a synchronous Nominatim request plus a
        `QApplication.processEvents()` on the GUI thread. Both are forbidden by
        SPEC-MAP-001 (INV-1 and the named `processEvents` trap). The offline
        nearest-capital answer is returned instead; real names now arrive via
        `_name_worker`.
        """
        return self._nearest_capital(lat, lon)

    def _detect_timezone(self, lat: float, lon: float):
        """Resolve the IANA timezone. Local and synchronous by design.

        The timezone is chart-affecting, so unlike the place NAME it must be
        final before `location_selected` fires (INV-3). That is affordable
        because `core.tz_finder` pre-warms the finder: the lookup itself is
        0.7 ms. Only a click within the first ~800 ms of the map opening can
        wait, and that wait is bounded.
        """
        self.detected_timezone = None

        from core.tz_finder import timezone_at_or_offset, is_ready
        if not is_ready():
            # Rare: the user beat the warm-up. This is the ONE place the
            # loading overlay is still the right answer.
            lm = self._loading()
            if lm:
                lm.start("Loading timezone data...")
            try:
                tz_name = timezone_at_or_offset(lat, lon, timeout=10.0)
            finally:
                if lm:
                    lm.finish()
        else:
            # ...or_offset, never plain timezone_at: a click on OPEN WATER has
            # no timezone polygon, so timezone_at returns None, and the
            # consumer treats None as "leave the field alone" — the previous
            # city's timezone then survived into a different location's chart.
            tz_name = timezone_at_or_offset(lat, lon)

        if not tz_name:
            self.timezone_label.setText("TZ: --")
            return

        self.detected_timezone = tz_name
        try:
            from datetime import datetime
            import pytz
            offset = datetime.now(pytz.timezone(tz_name)).strftime('%z')
            self.timezone_label.setText(
                f"TZ: {offset[:3]}:{offset[3:]} ({tz_name})")
        except Exception:
            self.timezone_label.setText(f"TZ: {tz_name}")

    def get_detected_timezone(self) -> Optional[str]:
        """Get the detected timezone name"""
        return self.detected_timezone

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    def set_marker(self, lat: float, lon: float, city: str = "", country: str = ""):
        """Set marker position from an external source (Edit Info coordinates,
        a chart load, the picker dialog's initial position).

        This MUST invalidate in-flight async work like a click does. It did not,
        and the hole was reachable: click A to start a reverse geocode, then
        type coordinates for B in the Info tab — A's reply landed and was
        written in as B's city and country.
        """
        self._bump_selection()
        self._name_gen = -1
        self._search_gen = -1
        self._name_worker.cancel()
        self._search_worker.cancel()

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
            self.map_widget.set_marker(
                lat, lon, label=self.current_city or self.current_country or "")
            self.map_widget.set_position(lat, lon)

        # Detect timezone
        self._detect_timezone(lat, lon)

        # SPEC-MAP-002: an externally-set marker is still a selection, so the
        # card and the bands' instant follow it. Restoring a chart must not
        # leave the card showing the PREVIOUS chart's place.
        self._refresh_card_ascendant()
        if self.asc_controller is not None:
            self.asc_controller.request_bands(lat, lon)

    # =========================================================================
    # THEME SUPPORT
    # =========================================================================

    # ---- td-iqjb.7 (Wave G): live theme re-apply for the map chrome ----
    # Each style_fn re-reads get_theme_colors() + is_light_theme() on every call
    # so a replay re-decides light/dark polarity. NEVER capture a pre-rendered
    # string (ThemedStyleMixin contract; re-freeze bug it exists to prevent).

    def _map_bar_colors(self):
        """Derived bar/input colors, re-decided from the CURRENT theme."""
        from ui.qt_theme import is_light_theme
        theme = get_theme_colors()
        light = is_light_theme()
        return {
            'theme': theme,
            'bar_bg': theme['secondary'] if light else SURFACE,
            'bar_border': theme['secondary_light'] if light else BORDER,
            'input_bg': theme['secondary_dark'] if light else BG,
            'input_text': theme['secondary_text'],
        }

    def _search_frame_style(self):
        c = self._map_bar_colors()
        return f"""
            QFrame {{
                background-color: {c['bar_bg']};
                border-bottom: 2px solid {c['theme']['primary']};
                padding: 8px;
            }}
        """

    def _search_label_style(self):
        c = self._map_bar_colors()
        return f"color: {c['input_text']}; font-size: {scaled_area_px('buttons')}px;"

    def _search_entry_style(self):
        c = self._map_bar_colors()
        return f"""
            QLineEdit {{
                background-color: {c['input_bg']};
                color: {c['input_text']};
                border: 2px solid {c['bar_border']};
                border-radius: 6px;
                padding: 10px 14px;
                font-size: {scaled_area_px('buttons')}px;
                font-weight: 500;
            }}
            QLineEdit:focus {{
                border: 2px solid {c['theme']['primary']};
            }}
        """

    def _search_btn_style(self):
        theme = get_theme_colors()
        return f"""
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
        """

    def _asc_btn_style(self):
        """Checkable toggle: outlined when off, filled accent when on.

        Two states in one sheet rather than restyling on toggle — a toggle
        handler that restyles is a handler a live theme switch can miss.
        """
        theme = get_theme_colors()
        c = self._map_bar_colors()
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {c['input_text']};
                border: 1px solid {theme['primary']};
                border-radius: 6px;
                padding: 9px 14px;
                font-size: {scaled_area_px('buttons')}px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {theme['primary_light']};
                color: white;
            }}
            QPushButton:checked {{
                background-color: {theme['primary']};
                color: white;
                font-weight: bold;
            }}
        """

    def _search_status_style(self):
        c = self._map_bar_colors()
        return f"color: {c['input_text']}; font-size: {scaled_area_px('info_text')}px;"

    def _apply_bar_frame_style(self):
        c = self._map_bar_colors()
        return f"""
            QFrame {{
                background-color: {c['bar_bg']};
                border-top: 1px solid {c['bar_border']};
                padding: 8px;
            }}
        """

    def _selection_status_style(self):
        theme = get_theme_colors()
        return f"color: {theme['secondary_text']}; font-size: {scaled_area_px('info_text')}px;"

    def _apply_btn_style(self):
        theme = get_theme_colors()
        return f"""
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
        """

    def refresh_theme(self):
        """Update colors after theme change (td-iqjb.7 Wave G).

        Replays every registered search-bar / apply-bar style under the current
        palette (was a bare `pass` -> black search strip + pale chips survived a
        live switch).

        SPEC-MAP-001 INV-6 closes the hole this docstring used to record. The
        map is no longer "bright in both themes and needs no restyle": it now
        re-renders every resident tile through the dark palette transform and
        re-reads its background brush from the theme.

        NOTE (justified residual): the FALLBACK path in _create_map_widget styles
        its manual-entry frames from FROZEN module constants (BG/SURFACE/BORDER/
        TEXT_*). It renders only when the offline map is unavailable -- the tile DB
        is absent OR OfflineMapWidget construction raises (both rare: the tile
        cache is bundled and construction normally succeeds).
        """
        self._replay_themed()
        if self.has_map and self.map_widget is not None:
            self.map_widget.refresh_theme()
        # SPEC-MAP-002: the card carries its own registry, and the map's chrome
        # (pin, band labels, graticule) bakes theme colours into brushes at
        # build time — map_widget.refresh_theme() rebuilds those. Without this
        # cascade the card would keep the old palette, which is exactly the
        # class of hole td-iqjb.7 was opened to close.
        if self.info_card is not None:
            self.info_card.refresh_theme()
