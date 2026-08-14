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
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QFrame,
    QGridLayout,
    QLineEdit,
)
from PySide6.QtCore import Signal, Slot, Qt

# Theme imports
from ui.qt_theme import (
    BG,
    SURFACE,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    BORDER,
    STATUS,
    get_theme_colors,
    get_theme_accent,
    scaled_area_px,
)
from ui.themed_style import ThemedStyleMixin

def _default_db_path():
    from state.user_data import get_project_root
    return os.path.join(str(get_project_root()), "map_tiles_cache.db")

DEFAULT_DB_PATH = _default_db_path()

#: Zoom a successful search lands on (SPEC-MAP-001 D-10).
#: This MUST stay at the cached ceiling. It was 8 — one level past the last
#: cached level — which made every visible tile a serial network fetch on the
#: GUI thread and is the whole reason a search froze the app for 10-20 s.
from apps.widgets.map_tiles import SOFT_MAX_ZOOM as MAP_SEARCH_ZOOM

#: How far a reverse-geocoded name may be from the current selection before it
#: is treated as belonging to a different place and dropped. The geocode cache
#: is keyed at two decimal places (~1.6 km at the equator), so the tolerance
#: has to clear that comfortably while still being smaller than the distance
#: at which a name stops describing where the pin is.
NAME_MATCH_MAX_KM = 25.0

class EditMapSubTab(ThemedStyleMixin, QWidget):
    """
    Interactive map sub-tab for location selection.

    Signals:
        location_selected(float, float, str, str): lat, lon, city, country
        apply_requested(object): Apply button clicked; carries the current
            RoutedSelection (or None) so the host adopts it ONCE and switches
            rows, without re-entering selection_routed (SPEC-MAP-004 §4.5).
    """

    location_selected = Signal(float, float, str, str)
    #: SPEC-MAP-004 §4.2. Carries a `RoutedSelection`: the point, its timezone,
    #: its name, whether it was snapped and from where, the generation, and
    #: `is_final`. Hosts and add-ons read THIS; `location_selected` survives
    #: only until the last host is converted, because it cannot carry a
    #: timezone and a host that has to re-derive one is how F-1 happened.
    selection_routed = Signal(object)
    #: SPEC-MAP-004 §4.5. Deliberate Apply re-entry, distinct from a selection
    #: delivery: carries the current `RoutedSelection` (or None if nothing is
    #: selected) so the host applies that ONE payload and switches rows.
    apply_requested = Signal(object)
    #: SPEC-MAP-004 Wave 4 (§4.6, the public extension surface). Re-emits the
    #: inner tile widget's `zoom_changed` so hosts subscribe to the SUBTAB, not
    #: to `.map_widget.map_widget` (the private inner widget). Emits nothing
    #: when the map failed to build (`has_map` False) — there is no inner signal
    #: to relay, and a host that connected still just never hears one.
    zoom_changed = Signal(int)
    #: emitted the moment a user STARTS a place search (not when it resolves), so
    #: a host with its own async place work (the New & Edit parse-geocode bridge,
    #: WI-4) can supersede it before a stale result preempts the search.
    search_started = Signal()

    _shared_timezone_finder = None
    _shared_geolocator = None

    def __init__(self, parent_panel):
        super().__init__()

        self.parent_panel = parent_panel
        self.detected_timezone = None
        self.current_lat = None
        self.current_lon = None
        self.current_city = ""
        self.current_country = ""

        # SPEC-MAP-004 §4.3: the extension surface. Hosts ADD `MapAddon`s (the
        # apply bar is one — Edit Chart attaches it explicitly); the subtab
        # cascades theme and routed selections to them and tears them down.
        # Never subtracted from — there is no "hide the bar" flag any more
        # (W3c): a bar exists only where a host asked for one.
        self._addons = []

        # SPEC-MAP-004 §4.2: how THIS host interprets a click. Default: never
        # snap. A host that wants its clicks moved to a capital states how far
        # it is willing to move the user (SPEC-MAP-003 INV-5 — no default
        # distance), and unbounded snapping is not expressible at all.
        from core.map_selection import SelectionPolicy
        self._selection_policy = SelectionPolicy()
        self._last_routed = None
        self._delivered_final_gen = -1

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
        #: Last basis pushed via set_time_basis, retained so an AscendantAddon
        #: attached afterwards can replay it (W4 Half B review). None until a
        #: host pushes one; the Ascendant hosts that never push leave it None.
        self._pending_time_basis = None

        # True while the card is showing the SELECTION rather than a hovered
        # point. A late reverse-geocode may repaint the card only in that
        # state, otherwise it would drag the card off the point the user is
        # pointing at.
        self._card_shows_selection = False

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
        # Retain the last basis unconditionally so an AscendantAddon attached
        # AFTER the host pushed it can replay it in attach() (W4 Half B review):
        # without this a late attach builds a blank controller and the preview
        # stays inert until the host happens to re-push. Edit Chart attaches
        # before it ever calls this, so the replay is a no-op there — the point
        # is to keep the documented late-attach contract honest.
        self._pending_time_basis = (local_fields, mode, ayanamsa, sign_names,
                                    utc_input)
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

        self._card_shows_selection = False
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
        self._card_shows_selection = True
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
        # Add-ons append to this layout (below the map). Held so `add_addon`
        # can attach after construction, e.g. a host's Ascendant add-on (W4).
        self._root_layout = layout

        # === Search Bar (at top) ===
        self._create_search_bar(layout)

        # === Map Widget (takes most space) ===
        self._create_map_widget(layout)

        # === Apply Button Bar ===
        # W3c: the subtab no longer builds an apply bar. A host that wants one
        # ADDS it — Edit Chart calls `map_tab.add_addon(ApplyBarAddon())`. Every
        # other host (dialogs, Eclipse, Lunar New Year, Birth Finder) simply
        # never adds it, which is what the old `show_apply_bar=False` meant.

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
        # objectName so the border-bottom selector below can be scoped to THIS
        # frame only. A bare `QFrame { border-bottom }` also matches every QLabel
        # descendant (QLabel is a QFrame subclass), painting a second 2px accent
        # stub under each label in the row (WI-12). QLineEdit/QPushButton are not
        # QFrame subclasses, which is why only the labels showed a stub.
        _search_frame = QFrame()
        _search_frame.setObjectName("mapSearchRow")
        self.search_frame = self._register_themed(_search_frame, self._search_frame_style)
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
                # SPEC-MAP-004 Wave 4: relay the inner zoom signal out through
                # the subtab so hosts never subscribe to the private inner
                # widget. Signal-to-signal connect re-emits with the same int.
                self.map_widget.zoom_changed.connect(self.zoom_changed)
                self._zoom_relay_connected = True
                self.map_widget.set_graticule_visible(True)
                self.has_map = True

                # SPEC-MAP-002 §4.4: the card is a child of the VIEWPORT, so it
                # stays pinned to the corner while the map pans under it.
                from apps.widgets.map_info_card import MapInfoCard
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
                # SPEC-MAP-004 Wave 4 Half B: the Ascendant preview is no longer
                # built here for every host. It is an opt-in AscendantAddon —
                # only Edit Chart, the one host that edits a birth instant, adds
                # it, which publishes `self.asc_controller`. Every subtab path
                # that drives it is already None-guarded, so a host without the
                # add-on simply has no preview. The hover eventFilter stays
                # installed (it no-ops when asc_controller is None) so attaching
                # the add-on later needs no re-wiring.
                self.map_widget.viewport().installEventFilter(self)

                parent_layout.addWidget(self.map_widget, stretch=1)
                return
            except Exception as e:
                print(f"Failed to create offline map widget: {e}")
                # A step AFTER the widget was built (info card, event filter) can
                # throw. The widget is a live QObject with a running tile thread
                # and — since W4 — a connected zoom relay; the fallback below
                # nulls our references, which would ORPHAN it (leaked thread, a
                # relay still re-emitting into a subtab that reports has_map
                # False, and shutdown() skipping it because it trusts has_map).
                # Dispose it while we still hold the handle (review finding).
                stale = self.map_widget
                if stale is not None:
                    try:
                        stale.zoom_changed.disconnect(self.zoom_changed)
                    except (RuntimeError, TypeError):
                        pass
                    try:
                        stale.shutdown()
                    except Exception:
                        pass
                    try:
                        stale.setParent(None)
                        stale.deleteLater()
                    except RuntimeError:
                        pass
                # The info card is a CHILD of the stale viewport, so deleting the
                # widget above also deletes the card's C++ object — but the
                # Python reference would dangle, and refresh_theme()/set_marker()
                # would then touch a deleted object and raise (review finding).
                # Drop it so the fallback surface has no card, matching has_map.
                self.info_card = None

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

    def add_addon(self, addon):
        """Register and attach a `MapAddon` (SPEC-MAP-004 §4.3).

        The one way chrome is added to the shared component. The add-on builds
        into the root layout, receives every routed selection (fan-out from
        `_apply_location`), is re-themed by `refresh_theme`, and is torn down by
        `shutdown`. Returns the add-on so a caller can hold a reference.
        """
        self._addons.append(addon)
        addon.attach(self, self._root_layout)
        return addon

    def _notify_addons_selection(self, routed):
        """Fan a routed delivery out to every attached add-on."""
        for addon in self._addons:
            try:
                addon.on_selection(routed)
            except Exception:
                # An add-on must never break the component's own delivery.
                pass

    # --- SPEC-MAP-004 Wave 4: public map-surface forwarders ------------------
    # Hosts that draw on the map (Eclipse, Lunar New Year) used to reach through
    # `subtab.map_widget.map_widget.<method>` — two hops into the PRIVATE inner
    # tile widget. That coupling is what the T-3 sweep now forbids: a host that
    # names the inner widget also owns its None-guarding, its lifecycle, and
    # every rename of it. These forwarders make the subtab the single public
    # surface. Each is a no-op when the map failed to build (`has_map` False,
    # `map_widget` None) — the same silent-degrade contract the inner setters
    # already have, so a host need not repeat the `hasattr(...map_widget)` dance.

    def add_overlay_polygon(self, coords, fill="#FF000040", border="#FF0000",
                            width=2.0, persistent=True):
        """Draw a filled polygon overlay; return the item (None if no map).

        Full pass-through of the inner signature INCLUDING `persistent` and the
        returned QGraphicsItem — a forwarder that narrowed either would quietly
        change the contract a future caller depends on (review finding)."""
        if self.has_map and self.map_widget is not None:
            return self.map_widget.add_overlay_polygon(
                coords, fill, border, width, persistent)
        return None

    def add_overlay_line(self, coords, color="#FF0000", width=2.0,
                         persistent=True):
        """Draw a polyline overlay; return the item (None if no map)."""
        if self.has_map and self.map_widget is not None:
            return self.map_widget.add_overlay_line(
                coords, color, width, persistent)
        return None

    def clear_overlays(self):
        """Remove every drawn overlay. No-op if the map did not build."""
        if self.has_map and self.map_widget is not None:
            self.map_widget.clear_overlays()

    def set_position(self, lat, lon):
        """Recentre the map on (lat, lon). No-op if the map did not build."""
        if self.has_map and self.map_widget is not None:
            self.map_widget.set_position(lat, lon)

    def _connect_signals(self):
        """Wire up signal connections.

        The Apply button is now owned and wired by `ApplyBarAddon.attach`
        (W3b), so there is nothing flag-dependent left to connect here.
        """
        pass

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

        # A user search is a fresh place intent: tell hosts NOW (WI-4), before
        # the async result, so their own in-flight place work stands down.
        self.search_started.emit()
        self._status("Searching...")
        # Remember whether the user qualified the town with a country/region.
        # Many towns share a name across countries (Brunswick: Germany, Maine,
        # Georgia, Melbourne...), and Nominatim silently picks its top hit, so
        # a bare one-word query gets an ambiguity warning when it resolves.
        self._search_had_qualifier = ',' in query or ' ' in query
        # No loading_manager here: a modal overlay was the visible symptom of a
        # blocking call, and there is no longer a blocking call to cover.
        self._search_gen = self._bump_selection()
        self._search_worker.request_forward(query)

    def _bump_selection(self) -> int:
        """Invalidate every async result that has not landed yet.

        Called by search, click and set_marker alike, so whichever input the
        user made LAST wins regardless of which network reply is slowest.

        Superseding an unfinished generation TERMINATES it first (INV-9). A
        pending reverse geocode is about to be thrown away, so without this the
        generation it belonged to would never end: `set_marker` after a click,
        or a search that then fails, both left a consumer waiting for an
        `is_final` that could no longer arrive. The terminal carries the same
        values that generation already delivered, so a host re-writes what it
        already has, in the same synchronous call, immediately before the new
        selection overwrites it.
        """
        self._deliver_terminal()
        self._sel_gen += 1
        return self._sel_gen

    @Slot(object)
    def _on_search_resolved(self, result):
        """Worker came back. Drop it if the user has since picked elsewhere."""
        if self._search_gen != self._sel_gen:
            return                      # a click or another search superseded it
        if result is None:
            self._status("❌ Not found. Try 'Town, Country' "
                         "(e.g. 'Brunswick, Germany')", STATUS['error'])
            return

        if self.has_map and self.map_widget:
            self.map_widget.set_marker(result.lat, result.lon)
            self.map_widget.set_position(result.lat, result.lon)
            # D-10: the cached ceiling, not 8. This one line is the difference
            # between instant and a ~50-tile serial network storm.
            self.map_widget.set_zoom(MAP_SEARCH_ZOOM)

        self._apply_selection(result.lat, result.lon,
                              city=result.city, country=result.country,
                              resolve_name=not (result.city or result.country),
                              origin="search")

        label = result.label or f"{result.lat:.4f}, {result.lon:.4f}"
        if getattr(self, '_search_had_qualifier', True):
            self._status(f"✓ Found: {label[:50]}", STATUS['success'])
        else:
            # One-word query: the hit may be the wrong same-name town.
            # Show WHICH one was picked and how to override it.
            self._status(f"⚠ Found: {label[:40]}. Wrong one? "
                         "Search 'Town, Country'", STATUS['warning'])
        self.search_status.setToolTip(label)

    def apply_geocode_result(self, result, origin: str = "parse",
                             had_qualifier: bool = True):
        """WI-4: land a place geocoded OUTSIDE the map (the token-bar parse
        bridge) through the same commit a search uses, but tagged with its
        ``origin`` so the host can tell a derived pin-move from a user one.

        This owns its OWN transaction (marker + view + zoom + selection) and its
        OWN ambiguity warning — it is deliberately NOT a shared closure with
        ``_on_search_resolved``, whose warning lives inside ``_on_search`` and so
        would never fire on this path. ``had_qualifier=False`` (a bare one-word
        place) gets the same "wrong same-name town?" hint a one-word search does;
        the parse bridge sends "City, Country" and so is qualified in practice.

        A ``None`` result leaves the existing coordinates UNTOUCHED (never 0/0,
        never a cleared pin) and says so on the status line (F-1 stays retired).
        """
        if result is None:
            self._status("Place not found — pin unchanged", STATUS['warning'])
            return

        if self.has_map and self.map_widget:
            self.map_widget.set_marker(result.lat, result.lon)
            self.map_widget.set_position(result.lat, result.lon)
            # D-10 / zoom-7 tile ceiling: SOFT_MAX is fully cached, so this is
            # instant instead of a serial network tile storm.
            self.map_widget.set_zoom(MAP_SEARCH_ZOOM)

        self._apply_selection(result.lat, result.lon,
                              city=result.city, country=result.country,
                              resolve_name=not (result.city or result.country),
                              origin=origin)

        label = result.label or f"{result.lat:.4f}, {result.lon:.4f}"
        if had_qualifier:
            self._status(f"✓ {label[:50]}", STATUS['success'])
        else:
            self._status(f"⚠ {label[:40]}. Wrong one? "
                         "Add the country", STATUS['warning'])
        self.search_status.setToolTip(label)

    @Slot()
    def _on_detent_reached(self):
        """Wheel zoom hit the offline boundary (INV-4). Inline hint only."""
        self._status("Zoom limit — scroll again to load detailed tiles online")

    @Slot(float, float)
    def _on_map_clicked(self, lat: float, lon: float):
        """Handle map click - auto-applies location immediately"""
        # The coordinate labels are written INSIDE the transaction, from the
        # routed point. Written here, from the raw click, they would be the one
        # surface still showing the pre-snap coordinates on a snapping host.
        if self.has_map and self.map_widget:
            self.zoom_label.setText(f"Zoom: {self.map_widget.get_zoom()}")

        self._apply_selection(lat, lon, resolve_name=True)

    def _apply_selection(self, lat: float, lon: float, city: str = "",
                         country: str = "", resolve_name: bool = True,
                         origin: str = "click"):
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
        # This pick is now the truth. Anything still in flight for an older
        # pick — a slow search, an older reverse geocode — is dead.
        gen = self._bump_selection()

        # --- 1. the CLICKED point's timezone, resolved but not yet adopted --
        clicked_tz = self._resolve_timezone(lat, lon)

        # --- 2. route ONCE, before a single piece of state is committed -----
        # Everything below this line uses the ROUTED point. Routing at
        # emission time instead — the obvious-looking placement — leaves the
        # pin, the card, the timezone label and the pending reverse geocode
        # describing the raw click while the host charts the routed point.
        from core.map_selection import MapSelection, route_selection
        routed = route_selection(
            MapSelection(lat=lat, lon=lon, tz_name=clicked_tz,
                         city=city, country=country, is_final=not resolve_name,
                         origin=origin),
            self._selection_policy, sel_gen=gen)

        if routed.snapped:
            # A SNAPPED selection is already named, canonically, by the capitals
            # table — and that name is not decoration: a host matches it against
            # `WORLD_CAPITALS` to move its capitals dropdown. Letting the async
            # reverse geocode overwrite it re-spells the capital in the
            # geocoder's dialect ("Washington D.C." -> "Washington", verified
            # live against Nominatim by two reviewers), which drops the dropdown
            # match on the FINAL delivery only. Whether the combo followed the
            # snap then depended on whether the network answered, and the note
            # still read "Snapped to Washington D.C." beside a label saying
            # "Washington, United States" — two surfaces disagreeing, which is
            # the class this component exists to retire.
            #
            # So a snap is terminal on arrival: nothing better can be learned
            # about a point we deliberately moved to a known city, and the
            # round trip is skipped entirely.
            import dataclasses
            routed = dataclasses.replace(routed, is_final=True)
            resolve_name = False

        lat, lon = routed.lat, routed.lon
        lat_dir = "N" if lat >= 0 else "S"
        lon_dir = "E" if lon >= 0 else "W"

        # Committed BEFORE the display surfaces are painted: they read the
        # routed note from it, and a routed object assigned at the end of the
        # transaction would make every label one selection out of date.
        self._last_routed = routed

        self.current_lat = lat
        self.current_lon = lon
        self._commit_timezone(routed.tz_name)
        self.lat_label.setText(f"Lat: {abs(lat):.6f}° {lat_dir}")
        self.lon_label.setText(f"Lon: {abs(lon):.6f}° {lon_dir}")

        # --- 3. the name ---------------------------------------------------
        # Offline, and deliberately vague when it has to be: the routed
        # timezone is what supplies the country, and a capital's name is only
        # claimed when the click is ON that capital. A confidently wrong
        # "Toronto, Canada" over Indiana is worse than no city at all.
        self.current_city = routed.city
        self.current_country = routed.country
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
            self.map_widget.set_marker(
                lat, lon,
                label=routed.city or routed.country or "")
            if routed.snapped:
                # The point moved out from under the user's cursor. Bring the
                # view with it, or the pin lands off-screen and the snap looks
                # like nothing happened.
                self.map_widget.set_position(lat, lon)

        if hasattr(self, 'apply_btn'):
            self.apply_btn.setEnabled(True)

        # --- 4. the card, and the bands' instant (SPEC-MAP-002) -----------
        # Moving the selection moves its timezone, which moves the UTC instant
        # the bands belong to, so the scan is re-requested. It runs on a worker
        # and its result is generation-guarded, so this costs nothing here.
        self._refresh_card_ascendant()
        if self.asc_controller is not None:
            self.asc_controller.request_bands(lat, lon)

        # --- 5. the real name, asynchronously (INV-8 guards staleness) -----
        # Requested for the ROUTED coordinates: asking about the raw click
        # would patch the label with the name of a place we are no longer at.
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
        # The snap disclosure rides HERE, on the one place a user looks to
        # check where they are. A component that moves someone's click 700 km
        # and says only the destination's name has not told them anything.
        # Empty for every non-snapping host, which today is all of them.
        note = getattr(self._last_routed, "note", "") if self._last_routed else ""
        self.location_label.setText(f"{text}  ·  {note}" if note else text)
        if hasattr(self, 'selection_status'):
            self.selection_status.setText(
                f"📍 {text} ({abs(lat):.4f}° {lat_dir}, {abs(lon):.4f}° {lon_dir})")

    def _deliver_terminal(self):
        """End this generation with an `is_final=True` delivery (INV-9).

        Every generation must terminate on EVERY path, including the ones that
        found nothing: an offline failure, an empty answer, a reply about a
        point too far away. Those all used to `return` silently, which is
        invisible until something waits for the end — the picker dialog's
        `close_policy="final"` (a Wave 5 feature, not built yet) would then hang
        forever on exactly the pick that went wrong. Terminating on every path
        NOW is what makes that policy safe to add later. The terminal delivery
        carries the instant name, which is the best answer that exists.
        """
        if self._last_routed is None or self._last_routed.is_final:
            return
        import dataclasses
        from core.place_naming import (
            clamp_label, clean_place_parts, format_place_line)
        # Clean THEN clamp: this is the terminal RoutedSelection every host
        # consumes, so it must be stray-comma-clean whatever put the name on
        # current_city (the async reply cleans at its entry, but a future path
        # that sets current_city raw must not be able to leak a comma here).
        city = clamp_label(clean_place_parts(self.current_city or ""))
        country = clamp_label(clean_place_parts(self.current_country or ""))
        self._last_routed = dataclasses.replace(
            self._last_routed,
            city=city,
            country=country,
            # `display` is DERIVED from city/country, so replacing those two
            # and not this one leaves a single frozen object contradicting
            # itself — city='Fort Wayne' beside display='United States'. A host
            # that trusts `display` then paints the placeholder for ever.
            display=format_place_line(city, country,
                                      self._last_routed.lat,
                                      self._last_routed.lon),
            is_final=True)
        self._apply_location()

    @Slot(object)
    def _on_name_resolved(self, result):
        """A reverse geocode landed. Label only — never the coordinates."""
        if self._name_gen != self._sel_gen:
            return                      # names a location the user left
        if self.current_lat is None:
            return
        if result is None or not (result.city or result.country):
            # Nothing better than the instant name will arrive. Say so, rather
            # than leaving the generation open for ever (INV-9).
            self._deliver_terminal()
            return

        # The generation token proves the reply is not OUT OF DATE. It does not
        # prove the reply is about THIS POINT. Those are different claims, and
        # the second one is the one the user reads: a name is only ever shown
        # next to coordinates, so a name that belongs to different coordinates
        # is the very bug this whole change is about. The geocode cache is
        # keyed at ~1 km, so a small offset is expected and fine; anything
        # further apart than a city is a mismatch and is dropped rather than
        # displayed.
        from core.place_naming import haversine_km
        if haversine_km(self.current_lat, self.current_lon,
                        result.lat, result.lon) > NAME_MATCH_MAX_KM:
            self._deliver_terminal()
            return
        # Sanitise the geocoder's own fields here, at the entry point: a reverse
        # geocode can hand back 'Ermont,' and this name reaches the pin label,
        # the card AND the terminal RoutedSelection. route_selection cleans the
        # click's instant name, but this ASYNC reply never passes through it, so
        # without cleaning here the stray comma survives to every host (INV-5).
        from core.place_naming import clean_place_parts
        self.current_city = clean_place_parts(result.city) or self.current_city
        self.current_country = clean_place_parts(result.country) or self.current_country

        lat, lon = self.current_lat, self.current_lon
        self._show_selection(lat, lon,
                             "N" if lat >= 0 else "S", "E" if lon >= 0 else "W")

        # The status bar is NOT the only surface wearing this name. Patching
        # only `location_label`/`selection_status` left the pin and the info
        # card showing the placeholder for ever, which is what the bug report
        # actually described: coordinates and timezone right, three different
        # widgets all still saying the placeholder. Same text, every surface.
        if self.map_widget is not None:
            self.map_widget.set_marker_label(
                self.current_city or self.current_country or "")
        if self._card_shows_selection:
            # Only when the card is currently showing the SELECTION. If the
            # pointer has wandered off and the card is displaying a hovered
            # point, a late geocode must not yank it back.
            self._refresh_card_ascendant()

        # Re-emit so the form picks up the better name, and mark the
        # generation finished. Coordinates and the timezone are byte-identical
        # to what the transaction already applied.
        self._deliver_terminal()

    def _on_manual_coordinates(self):
        """Handle manual coordinate entry (fallback mode)"""
        try:
            lat = float(self.manual_lat.text())
            lon = float(self.manual_lon.text())

            if not (-90 <= lat <= 90):
                raise ValueError("Latitude must be -90 to 90")
            if not (-180 <= lon <= 180):
                raise ValueError("Longitude must be -180 to 180")

            # ONE call. `_on_map_clicked` already reaches `_apply_location`
            # through the selection transaction; the second call that used to
            # sit here emitted a byte-identical duplicate, so removing it
            # changes no behaviour — but it made the per-path delivery counts
            # depend on which path you arrived by, and INV-9's gate is
            # unwritable against a path that emits an arbitrary number of
            # times.
            self._on_map_clicked(lat, lon)

        except ValueError as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Invalid Coordinates", str(e))

    @Slot()
    def _apply_location(self):
        """Deliver the current selection to the host and to every add-on.

        Two signals during the migration. `selection_routed` is the real one:
        it carries the timezone, the snap origin, the generation and
        `is_final`. `location_selected` is the four-argument legacy form, kept
        until the last host is converted — it cannot carry a timezone, which
        is why every host that used it had to re-derive one, which is how F-1
        and the coordinate-blind cache both happened.
        """
        if self.current_lat is None or self.current_lon is None:
            return

        # ONE snapshot feeds both signals. `selection_routed` may be a direct
        # connection, so a slot can run synchronously and mutate the component
        # — a host calling set_marker from its own handler — and then the
        # legacy emission below would read the state that slot left behind.
        # Demonstrated: routed Paris, legacy Tokyo, from a single call.
        routed = self._last_routed
        lat, lon = self.current_lat, self.current_lon
        city, country = self.current_city, self.current_country

        # A generation is delivered as final ONCE. The Apply button re-enters
        # here, and without this a named pick emitted (gen 1, final) at
        # selection time and (gen 1, final) again on Apply — two terminals for
        # one generation, straight through INV-9. The legacy signal still fires
        # every time: Apply has always meant "hand this to the form again".
        if routed is not None:
            if routed.is_final and self._delivered_final_gen == routed.sel_gen:
                routed = None
            else:
                if routed.is_final:
                    self._delivered_final_gen = routed.sel_gen
                self.selection_routed.emit(routed)
                # Same routed answer the hosts get, fanned out to the add-ons
                # (SPEC-MAP-004 §4.3). set_marker deliberately does NOT reach
                # here (it never emits), so add-ons that must react to the
                # form-driven marker cannot rely on this alone.
                self._notify_addons_selection(routed)

        self.location_selected.emit(lat, lon, city, country)

    @Slot()
    def _apply_location_and_return(self):
        """Apply button: hand the current selection to the host form again and
        switch back (SPEC-MAP-004 §4.5).

        Does NOT call `_apply_location()`. That path re-emits `selection_routed`,
        which the host also adopts, AND `apply_requested` fires — so a non-final
        routed selection was adopted twice, with two `chart_modified` emissions.
        `selection_routed` reports SELECTION deliveries; Apply is deliberate
        re-entry and rides its own signal.

        Two things still happen, exactly as before:
        - the legacy four-argument `location_selected` fires once (the
          transitional contract every legacy listener still relies on until W7;
          `test_map_transaction.py` pins it);
        - `apply_requested` carries the current `_last_routed`, so the converted
          host adopts that ONE payload and switches rows. `set_marker` keeps
          `_last_routed` current without a network request, so Apply after
          Edit-Info coordinate typing is covered too.
        """
        if self.current_lat is None or self.current_lon is None:
            # Nothing selected. Still switch rows; adopt nothing.
            self.apply_requested.emit(None)
            return
        # Snapshot BOTH payloads BEFORE either emission. `location_selected`
        # runs its slots synchronously, so a legacy listener that reacts by
        # calling `set_marker()` would replace `_last_routed` before
        # `apply_requested` reads it — the two signals would then carry
        # DIFFERENT selections (the routed-Paris / legacy-Tokyo split that
        # `_apply_location` snapshots against, review finding).
        lat, lon = self.current_lat, self.current_lon
        city, country = self.current_city, self.current_country
        routed = self._last_routed
        self.location_selected.emit(lat, lon, city, country)
        self.apply_requested.emit(routed)

    # =========================================================================
    # UTILITIES
    # =========================================================================

    def _instant_place_name(self, lat: float, lon: float) -> Tuple[str, str]:
        """The placeholder name shown the moment the user clicks (INV-1).

        Offline and instant. `core.place_naming` decides: a capital only when
        the click is on it, otherwise the country of the timezone step 1 has
        just resolved for this same point, otherwise nothing.

        `self.detected_timezone` is used rather than a fresh lookup precisely
        because step 1 already paid for it — naming must add no latency.
        """
        from core.place_naming import instant_place_name
        return instant_place_name(lat, lon, self.detected_timezone)

    @staticmethod
    def _nearest_capital(lat: float, lon: float) -> Tuple[str, str]:
        """Closest known capital, by great-circle distance.

        Kept for external callers only. Nothing in the naming path uses it any
        more: an unbounded nearest-capital search always returns something, and
        "something" 700 km away is the Toronto-over-Indiana bug. Use
        `_instant_place_name`.
        """
        from core.place_naming import nearest_capital
        name, country, _km = nearest_capital(lat, lon)
        return name, country

    def _reverse_geocode(self, lat: float, lon: float) -> Tuple[str, str]:
        """Deprecated: kept only so external callers do not break.

        This used to run a synchronous Nominatim request plus a
        `QApplication.processEvents()` on the GUI thread. Both are forbidden by
        SPEC-MAP-001 (INV-1 and the named `processEvents` trap). The offline
        nearest-capital answer is returned instead; real names now arrive via
        `_name_worker`.
        """
        return self._instant_place_name(lat, lon)

    def _resolve_timezone(self, lat: float, lon: float) -> Optional[str]:
        """The IANA timezone for a point. Local, synchronous, no state written.

        Split out from `_detect_timezone` for SPEC-MAP-004 §4.2: the clicked
        point's zone has to be RESOLVED before routing (it is an input to it)
        but COMMITTED only after, because on a snapping host the zone that
        ends up on screen is the capital's, not the click's. Resolving and
        committing in one step is what made routing-at-emission produce a
        component showing one place while the host charted another.

        The timezone is chart-affecting, so unlike the place NAME it must be
        final before the selection is emitted (INV-3). That is affordable
        because `core.tz_finder` pre-warms the finder: the lookup itself is
        0.7 ms. Only a click within the first ~800 ms of the map opening can
        wait, and that wait is bounded.
        """
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

        return tz_name or None

    def _commit_timezone(self, tz_name: Optional[str]):
        """Adopt a resolved timezone as the component's answer, and show it.

        Takes the ROUTED zone, which on a snapping host is the capital's. None
        is displayed as unresolved and left as None — never defaulted to UTC
        and never left holding the previous selection's value (INV-3).
        """
        self.detected_timezone = tz_name

        if not tz_name:
            self.timezone_label.setText("TZ: --")
            return

        try:
            from datetime import datetime
            import pytz
            # td-yddt: display-only label. Compute the offset at the BIRTH
            # instant when the host gave us one (set_time_basis), so a
            # historical chart shows its own era's offset; fall back to now()
            # for hosts with no single birth instant. The IANA name passed
            # downstream (detected_timezone) is unaffected either way.
            tz = pytz.timezone(tz_name)
            basis = None
            ac = getattr(self, "asc_controller", None)
            fields = ac.time_basis_fields() if ac is not None else None
            if fields:
                try:
                    basis = datetime(int(fields['year']), int(fields['month']),
                                     int(fields['day']),
                                     int(fields.get('hour', 12)),
                                     int(fields.get('minute', 0)))
                except (KeyError, ValueError, TypeError):
                    basis = None
            if basis is not None:
                if ac.time_basis_is_utc():
                    # UTC-mode form: basis IS a UTC instant, never a wall
                    # time in tz (Codex review catch: bare localize showed
                    # +01:00 for a 2024-03-31 01:30 UTC Paris instant).
                    aware = pytz.utc.localize(basis).astimezone(tz)
                else:
                    try:
                        aware = tz.localize(basis, is_dst=None)
                    except (pytz.exceptions.AmbiguousTimeError,
                            pytz.exceptions.NonExistentTimeError):
                        # DST-edge wall time: either reading is defensible
                        # for a display-only label; take pytz's default.
                        aware = tz.localize(basis)
                offset = aware.strftime('%z')
            else:
                offset = datetime.now(tz).strftime('%z')
            self.timezone_label.setText(
                f"TZ: {offset[:3]}:{offset[3:]} ({tz_name})")
        except Exception:
            self.timezone_label.setText(f"TZ: {tz_name}")

    def _detect_timezone(self, lat: float, lon: float):
        """Resolve and adopt a point's own timezone, in one step.

        The unrouted composition, kept for the paths that genuinely want the
        point's own zone with no policy applied (`set_marker`, host restores).
        The selection transaction does NOT use this — it needs the two halves
        apart so routing can sit between them.
        """
        self._commit_timezone(self._resolve_timezone(lat, lon))

    def set_selection_policy(self, policy):
        """Declare how this host interprets a click (SPEC-MAP-004 §4.2).

        Declared once at construction, and re-declared when the host's own
        mode changes — Eclipse's capitals combo. Takes effect on the NEXT
        selection; it never retroactively moves a point already picked.
        """
        self._selection_policy = policy

    def get_last_routed(self):
        """The last `RoutedSelection` this component produced, or None.

        For hosts and tests that need the routed answer outside the signal —
        a dialog reading it on accept, a gate asserting on it.
        """
        return self._last_routed

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

        # Timezone first: it is chart-affecting (INV-3) AND it is what the
        # offline name falls back to, so it has to be resolved before naming.
        self._detect_timezone(lat, lon)

        if city or country:
            # External callers (chart load, picker initial position) can pass a
            # name a geocoder produced; clean it here too, so the one that comes
            # from `_instant_place_name` below (already clean) and this one meet
            # the same contract (INV-5).
            from core.place_naming import clean_place_parts
            self.current_city = clean_place_parts(city or "")
            self.current_country = clean_place_parts(country or "")
        else:
            # No name supplied — recompute one for THIS point. Keeping the
            # previous selection's name here is how a chart loaded after
            # another one ended up labelled with its predecessor's city.
            # Offline only: set_marker fires on every coordinate keystroke in
            # Edit Info, so it must never reach the network.
            self.current_city, self.current_country = \
                self._instant_place_name(lat, lon)

        # Update displays
        lat_dir = "N" if lat >= 0 else "S"
        lon_dir = "E" if lon >= 0 else "W"
        self.lat_label.setText(f"Lat: {abs(lat):.6f}° {lat_dir}")
        self.lon_label.setText(f"Lon: {abs(lon):.6f}° {lon_dir}")
        # The status bar is a selection surface too — it must not keep naming
        # the place the previous marker was at.
        self._show_selection(lat, lon, lat_dir, lon_dir)

        # Enable confirm button since we have a valid location
        if hasattr(self, 'apply_btn'):
            self.apply_btn.setEnabled(True)

        # Update map
        if self.has_map and self.map_widget:
            self.map_widget.set_marker(
                lat, lon, label=self.current_city or self.current_country or "")
            self.map_widget.set_position(lat, lon)

        # SPEC-MAP-002: an externally-set marker is still a selection, so the
        # card and the bands' instant follow it. Restoring a chart must not
        # leave the card showing the PREVIOUS chart's place.
        self._refresh_card_ascendant()
        if self.asc_controller is not None:
            self.asc_controller.request_bands(lat, lon)

        # The routed answer follows too, or `get_last_routed()` and the next
        # Apply keep describing the point BEFORE this marker — which is the
        # F-1 shape exactly: correct component state, a stale chart-affecting
        # answer beside it. Routed with a never-snap policy on purpose: this
        # method is "put the marker HERE", from Edit Info coordinates or a
        # chart load, and a policy that relocated those would be moving a
        # point the user did not click. Final, and NOT emitted — set_marker is
        # driven by the form, and emitting back into it would loop.
        from core.map_selection import (MapSelection, SelectionPolicy,
                                        route_selection)
        self._last_routed = route_selection(
            MapSelection(lat=lat, lon=lon, tz_name=self.detected_timezone,
                         city=self.current_city, country=self.current_country,
                         is_final=True),
            SelectionPolicy(), sel_gen=self._sel_gen)

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
            QFrame#mapSearchRow {{
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
        # SPEC-MAP-004 §4.3 INV-8: every ATTACHED add-on re-themes too. The
        # add-ons' widgets are NOT in _replay_themed's registry (they own their
        # styling), so without this loop the apply bar keeps the old palette
        # through a live switch — the exact half-themed hole this cascade closes.
        for addon in self._addons:
            try:
                addon.refresh_theme()
            except Exception:
                pass
        if self.has_map and self.map_widget is not None:
            self.map_widget.refresh_theme()
        # SPEC-MAP-002: the card carries its own registry, and the map's chrome
        # (pin, band labels, graticule) bakes theme colours into brushes at
        # build time — map_widget.refresh_theme() rebuilds those. Without this
        # cascade the card would keep the old palette, which is exactly the
        # class of hole td-iqjb.7 was opened to close.
        if self.info_card is not None:
            self.info_card.refresh_theme()

    # =========================================================================
    # Teardown (INV-7)
    # =========================================================================

    def shutdown(self, drain: bool = True):
        """Quiesce the subtab: stop everything that could still emit into it.

        Public because four test files were reaching THROUGH the component to
        do this by hand (`tab._search_worker._pool.waitForDone(...)`), and each
        copy documented a different core-dump it was fixing. The order below is
        the one that does not dump core (measured: a bare `map_widget.shutdown()`
        left a half-torn-down widget whose geocode worker could still emit into
        it, and the process died with SIGSEGV ~1 run in 6, AFTER every test had
        passed):

        1. cancel both geocode generations, so any result that lands next is
           dropped by the INV-8 generation guard rather than reaching a scene
           that is going away;
        2. stop the Ascendant controller's band scan (its interval-0 timer runs
           on this thread and mutates the card / emits `bands_changed`; its own
           `shutdown()` is non-blocking, just aborts the scan);
        3. drain both worker pools, so no `_Job` is still running when the tile
           thread and scene are torn down (QThreadPool's destructor would
           otherwise block on a running job);
        4. take the tile thread down via the map widget's own `shutdown()`.

        THREADING: with `drain=True` (the default) step 3 BLOCKS (up to 5 s per
        worker) on a running network geocode, which cannot be interrupted. That
        is correct for offscreen tests and process teardown, where a `_Job` left
        running into process exit meets arbitrary widget-destruction order and
        the segfault window opens. It is WRONG on the live GUI thread, so a
        `closeEvent` auto-call is deliberately absent.

        `drain=False` is the GUI-owner variant (W3a): a picker dialog wires
        `dialog.finished -> shutdown(drain=False)` so closing returns instantly.
        This is safe because step 1's generation cancel already makes any late
        result inert (the INV-8 guard drops it); the drain only mattered for the
        process-exit case above.

        `drain=False` returns instantly ONLY while the owner keeps the closed
        dialog ALIVE — which both current owners do (neither `deleteLater`s the
        dialog; it stays a hidden child). Each live geocode `_Job` belongs to a
        child `QThreadPool`, and destroying that pool blocks on its runnable, so
        an immediate `deleteLater()` or `WA_DeleteOnClose` would just move the
        up-to-5 s wait from here into QObject destruction (measured ~1.1 s for a
        1 s job). A dialog that wants immediate teardown must therefore call the
        default `shutdown()` (drain=True) and accept the block, or keep the
        object alive as these do. These pickers are also ONE-SHOT: `shutdown()`
        is terminal (the tile thread is gone), so a reused dialog would reopen
        with a dead map — build a fresh dialog per open, as both owners do.

        Never gate the dialog's shutdown on `is_final` — it belongs to dialog
        END regardless of W5's `close_policy`, or `close_policy="final"` would
        tear down the very name worker it waits on.

        Quiesce ONLY: this does not destroy the widget. C++ destruction order
        stays with the owner (Rule 18) — a caller that also wants the object
        gone calls `deleteLater()` itself, while the application is still alive.
        Safe to call more than once and safe when the map failed to build
        (`has_map` is False, `map_widget` is None).
        """
        workers = [getattr(self, "_search_worker", None),
                   getattr(self, "_name_worker", None)]
        for worker in workers:
            if worker is not None:
                try:
                    worker.cancel()
                except RuntimeError:
                    pass
        asc = getattr(self, "asc_controller", None)
        if asc is not None:
            try:
                asc.shutdown()
            except RuntimeError:
                pass
        if drain:
            for worker in workers:
                if worker is not None:
                    try:
                        worker.wait(5000)
                    except RuntimeError:
                        pass
        if getattr(self, "has_map", False) and self.map_widget is not None:
            # W4: drop the zoom relay first, so a late inner emission cannot
            # re-emit through the subtab after it reports itself quiesced (the
            # signal-to-signal connect otherwise survives until the owner
            # deleteLater()s the widget — review finding). Idempotent: a second
            # shutdown() finds the one-shot flag already cleared and skips the
            # disconnect entirely (a blind re-disconnect makes Qt qWarn to
            # stderr before it raises, even inside a try/except).
            if getattr(self, "_zoom_relay_connected", False):
                self._zoom_relay_connected = False
                try:
                    self.map_widget.zoom_changed.disconnect(self.zoom_changed)
                except (RuntimeError, TypeError):
                    pass
            try:
                self.map_widget.shutdown()
            except RuntimeError:
                pass
        # SPEC-MAP-004 §4.3: tear the add-ons down too (detach removes their
        # widgets and drops the compatibility back-references). After the map so
        # a late delivery mid-teardown still finds a valid bar to disable.
        for addon in list(self._addons):
            try:
                addon.detach()
            except Exception:
                pass
        self._addons.clear()
