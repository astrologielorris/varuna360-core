# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Offline Map Widget - QGraphicsView-based map using SQLite tile cache

This widget provides an interactive world map that works completely offline
by reading pre-cached OpenStreetMap tiles from a SQLite database.

Features:
- Pan by dragging
- Zoom with mouse wheel
- Click to select location (returns lat/lon)
- Marker display for selected location
- Works with existing map_tiles_cache.db from tkintermapview
- Online tile fetching for zoom levels beyond cached tiles (requires internet)
"""

import os
import math
import sqlite3
import urllib.request
import urllib.error
from typing import Optional, Tuple

from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QGraphicsEllipseItem, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox
)
from PySide6.QtCore import Signal, Qt, QPointF, QRectF
from PySide6.QtGui import QPixmap, QPen, QBrush, QColor, QWheelEvent, QMouseEvent

# Tile size in pixels (standard OSM)
TILE_SIZE = 256

# Default database path
DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "map_tiles_cache.db"
)

# OSM tile server URL (standard format)
OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

# Extra zoom levels beyond cached tiles (fetched online)
EXTRA_ONLINE_ZOOM_LEVELS = 2

class TileCache:
    """
    Manages reading tiles from SQLite database with online fallback.

    For zoom levels beyond what's cached, tiles are fetched from OSM servers.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = None
        self.available_zooms = []
        self._online_cache: dict = {}  # In-memory cache for online tiles
        self._online_enabled = True  # Can be disabled if network fails repeatedly
        self._failed_fetches = 0  # Track consecutive failures
        self._connect()

    def _connect(self):
        """Connect to SQLite database"""
        if os.path.exists(self.db_path):
            try:
                self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
                # Get available zoom levels
                cursor = self.conn.cursor()
                cursor.execute("SELECT DISTINCT zoom FROM tiles ORDER BY zoom")
                self.available_zooms = [row[0] for row in cursor.fetchall()]
            except Exception as e:
                print(f"Failed to connect to tile cache: {e}")
                self.conn = None

    def get_tile(self, zoom: int, x: int, y: int) -> Optional[bytes]:
        """
        Retrieve a tile image from cache or fetch online.

        Args:
            zoom: Zoom level (0-19)
            x: Tile X coordinate
            y: Tile Y coordinate

        Returns:
            PNG image bytes or None if not found
        """
        # First try database cache
        if self.conn and zoom in self.available_zooms:
            try:
                cursor = self.conn.cursor()
                cursor.execute(
                    "SELECT tile_image FROM tiles WHERE zoom=? AND x=? AND y=?",
                    (zoom, x, y)
                )
                row = cursor.fetchone()
                if row and row[0]:
                    return row[0]
            except Exception as e:
                print(f"Error fetching tile z={zoom} x={x} y={y}: {e}")

        # Try in-memory cache for online tiles
        key = (zoom, x, y)
        if key in self._online_cache:
            return self._online_cache[key]

        # Try fetching online for extended zoom levels
        max_cached = max(self.available_zooms) if self.available_zooms else 6
        if zoom > max_cached and zoom <= max_cached + EXTRA_ONLINE_ZOOM_LEVELS:
            return self._fetch_online_tile(zoom, x, y)

        return None

    def _fetch_online_tile(self, zoom: int, x: int, y: int) -> Optional[bytes]:
        """
        Fetch a tile from OSM tile servers.

        Args:
            zoom: Zoom level
            x: Tile X coordinate
            y: Tile Y coordinate

        Returns:
            PNG image bytes or None if fetch failed
        """
        if not self._online_enabled:
            return None

        key = (zoom, x, y)
        url = OSM_TILE_URL.format(z=zoom, x=x, y=y)

        try:
            # Create request with proper User-Agent (required by OSM)
            request = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'Varuna360/1.0 (Astrology Application)'
                }
            )

            with urllib.request.urlopen(request, timeout=5) as response:
                tile_data = response.read()
                # Cache in memory
                self._online_cache[key] = tile_data
                self._failed_fetches = 0  # Reset failure counter
                return tile_data

        except urllib.error.URLError as e:
            self._failed_fetches += 1
            if self._failed_fetches >= 5:
                print(f"[MAP] Disabling online tiles after {self._failed_fetches} failures")
                self._online_enabled = False
            return None
        except Exception as e:
            self._failed_fetches += 1
            return None

    def get_max_zoom(self) -> int:
        """Get maximum available zoom level (includes online extension)"""
        base_max = max(self.available_zooms) if self.available_zooms else 6
        if self._online_enabled:
            return base_max + EXTRA_ONLINE_ZOOM_LEVELS
        return base_max

    def get_cached_max_zoom(self) -> int:
        """Get maximum zoom level available in local cache only"""
        return max(self.available_zooms) if self.available_zooms else 6

    def get_min_zoom(self) -> int:
        """Get minimum available zoom level"""
        return min(self.available_zooms) if self.available_zooms else 0

    def is_online_enabled(self) -> bool:
        """Check if online tile fetching is enabled"""
        return self._online_enabled

    def enable_online(self):
        """Re-enable online tile fetching"""
        self._online_enabled = True
        self._failed_fetches = 0

    def clear_online_cache(self):
        """Clear the in-memory cache of online tiles"""
        self._online_cache.clear()

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None

def lat_lon_to_tile(lat: float, lon: float, zoom: int) -> Tuple[int, int]:
    """
    Convert latitude/longitude to tile coordinates.

    Uses the standard OSM slippy map tile naming convention.
    """
    lat_rad = math.radians(lat)
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)

    # Clamp to valid range
    x = max(0, min(n - 1, x))
    y = max(0, min(n - 1, y))

    return x, y

def tile_to_lat_lon(x: float, y: float, zoom: int) -> Tuple[float, float]:
    """
    Convert tile coordinates (can be fractional) to latitude/longitude.

    Returns the lat/lon at the top-left corner of the tile.
    """
    n = 2 ** zoom
    lon = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    lat = math.degrees(lat_rad)

    return lat, lon

def pixel_to_lat_lon(pixel_x: float, pixel_y: float, zoom: int) -> Tuple[float, float]:
    """
    Convert pixel coordinates to latitude/longitude.

    Pixel coordinates are relative to the world at the given zoom level,
    where (0,0) is the top-left corner of tile (0,0).
    """
    tile_x = pixel_x / TILE_SIZE
    tile_y = pixel_y / TILE_SIZE
    return tile_to_lat_lon(tile_x, tile_y, zoom)

def lat_lon_to_pixel(lat: float, lon: float, zoom: int) -> Tuple[float, float]:
    """
    Convert latitude/longitude to pixel coordinates.
    """
    lat_rad = math.radians(lat)
    n = 2 ** zoom

    x = (lon + 180.0) / 360.0 * n * TILE_SIZE
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n * TILE_SIZE

    return x, y

class OfflineMapWidget(QGraphicsView):
    """
    Interactive map widget using cached OpenStreetMap tiles.

    Signals:
        location_clicked(float, float): Emitted when map is clicked with (lat, lon)
        location_changed(float, float): Emitted when marker position changes
    """

    location_clicked = Signal(float, float)
    location_changed = Signal(float, float)
    zoom_changed = Signal(int)  # Emitted when zoom level changes

    def __init__(self, db_path: str = None, parent=None):
        super().__init__(parent)

        # Initialize tile cache
        self.db_path = db_path or DEFAULT_DB_PATH
        self.tile_cache = TileCache(self.db_path)

        # Map state
        self.zoom = 2  # Start at world view
        self.center_lat = 25.0  # Centered on populated areas
        self.center_lon = 0.0

        # Marker position (None if no marker)
        self.marker_lat: Optional[float] = None
        self.marker_lon: Optional[float] = None
        self.marker_item: Optional[QGraphicsEllipseItem] = None

        # Overlay items (polygons, lines for Ascendant zones etc.)
        self.overlay_items: list = []
        # Persistent overlay data for redraw on zoom changes
        # Each entry: {'type': 'polygon'|'line', 'coords': [...], 'params': {...}}
        self._overlay_data: list = []

        # Dragging state
        self._dragging = False
        self._last_mouse_pos = QPointF()
        self._drag_start_pos = QPointF()  # Original press position for click detection
        self._did_drag = False  # True if mouse moved significantly during press

        # Loaded tile items (for cleanup)
        self._tile_items: dict = {}  # (zoom, x, y) -> QGraphicsPixmapItem

        # Setup scene and view
        self._setup_view()

        # Initial tile load
        self._load_visible_tiles()

    def _setup_view(self):
        """Configure the graphics view"""
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        # View settings
        self.setRenderHint(self.renderHints().SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)  # We handle drag manually
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        # Background color (ocean blue)
        self.setBackgroundBrush(QBrush(QColor("#b3d1ff")))

        # Set scene rect to world bounds at current zoom
        self._update_scene_rect()

    def _update_scene_rect(self):
        """Update scene rect based on current zoom level"""
        n = 2 ** self.zoom
        world_size = n * TILE_SIZE
        self.scene.setSceneRect(0, 0, world_size, world_size)

    def _load_visible_tiles(self):
        """Load tiles that are visible in the current viewport"""
        if not self.tile_cache.conn:
            return

        # Get viewport bounds in scene coordinates
        viewport_rect = self.mapToScene(self.viewport().rect()).boundingRect()

        # Calculate tile range
        n = 2 ** self.zoom

        min_tile_x = max(0, int(viewport_rect.left() / TILE_SIZE) - 1)
        max_tile_x = min(n - 1, int(viewport_rect.right() / TILE_SIZE) + 1)
        min_tile_y = max(0, int(viewport_rect.top() / TILE_SIZE) - 1)
        max_tile_y = min(n - 1, int(viewport_rect.bottom() / TILE_SIZE) + 1)

        # Load tiles
        for tx in range(min_tile_x, max_tile_x + 1):
            for ty in range(min_tile_y, max_tile_y + 1):
                self._load_tile(self.zoom, tx, ty)

        # Remove tiles that are too far from viewport (memory cleanup)
        self._cleanup_distant_tiles(min_tile_x - 2, max_tile_x + 2,
                                     min_tile_y - 2, max_tile_y + 2)

    def _load_tile(self, zoom: int, x: int, y: int):
        """Load a single tile from cache and add to scene"""
        key = (zoom, x, y)

        # Skip if already loaded
        if key in self._tile_items:
            return

        # Get tile from cache
        tile_data = self.tile_cache.get_tile(zoom, x, y)
        if not tile_data:
            return

        # Create pixmap from PNG data
        pixmap = QPixmap()
        if pixmap.loadFromData(tile_data):
            item = QGraphicsPixmapItem(pixmap)
            item.setPos(x * TILE_SIZE, y * TILE_SIZE)
            item.setZValue(0)  # Tiles at base level
            self.scene.addItem(item)
            self._tile_items[key] = item

    def _cleanup_distant_tiles(self, min_x: int, max_x: int, min_y: int, max_y: int):
        """Remove tiles outside the visible range"""
        to_remove = []
        for key, item in self._tile_items.items():
            z, x, y = key
            if z != self.zoom or x < min_x or x > max_x or y < min_y or y > max_y:
                to_remove.append(key)

        for key in to_remove:
            item = self._tile_items.pop(key)
            self.scene.removeItem(item)

    def _clear_all_tiles(self):
        """Remove all tiles from scene"""
        for item in self._tile_items.values():
            self.scene.removeItem(item)
        self._tile_items.clear()

    def set_position(self, lat: float, lon: float):
        """Center the map on the given coordinates"""
        self.center_lat = lat
        self.center_lon = lon
        self._center_on_position()

    def _center_on_position(self):
        """Center view on current lat/lon"""
        px, py = lat_lon_to_pixel(self.center_lat, self.center_lon, self.zoom)
        self.centerOn(px, py)
        self._load_visible_tiles()

    def set_zoom(self, zoom: int):
        """Set zoom level (clamped to available tiles)"""
        min_zoom = self.tile_cache.get_min_zoom()
        max_zoom = self.tile_cache.get_max_zoom()

        new_zoom = max(min_zoom, min(max_zoom, zoom))
        if new_zoom != self.zoom:
            self._clear_all_tiles()
            self.zoom = new_zoom
            self._update_scene_rect()
            self._center_on_position()
            self._update_marker()
            self._update_overlays()
            self.zoom_changed.emit(self.zoom)  # Notify listeners

    def get_zoom(self) -> int:
        """Get current zoom level"""
        return self.zoom

    def set_marker(self, lat: float, lon: float):
        """Place a marker at the given coordinates"""
        self.marker_lat = lat
        self.marker_lon = lon
        self._update_marker()
        self.location_changed.emit(lat, lon)

    def clear_marker(self):
        """Remove the marker"""
        self.marker_lat = None
        self.marker_lon = None
        if self.marker_item:
            self.scene.removeItem(self.marker_item)
            self.marker_item = None

    def _update_marker(self):
        """Update marker position on scene"""
        if self.marker_lat is None or self.marker_lon is None:
            return

        # Remove old marker
        if self.marker_item:
            self.scene.removeItem(self.marker_item)

        # Calculate pixel position
        px, py = lat_lon_to_pixel(self.marker_lat, self.marker_lon, self.zoom)

        # Create marker (red circle with white border)
        marker_size = 16
        self.marker_item = QGraphicsEllipseItem(
            px - marker_size/2, py - marker_size/2,
            marker_size, marker_size
        )
        self.marker_item.setPen(QPen(QColor("#FFFFFF"), 2))
        self.marker_item.setBrush(QBrush(QColor("#FF4444")))
        self.marker_item.setZValue(100)  # Above tiles
        self.scene.addItem(self.marker_item)

    # === Overlay Drawing Methods ===

    def add_overlay_polygon(self, coords: list, color: str = "#FF000040",
                           border_color: str = "#FF0000", border_width: float = 2.0,
                           persistent: bool = True):
        """
        Add a polygon overlay to the map.

        Args:
            coords: List of (lat, lon) tuples defining the polygon vertices
            color: Fill color with alpha (e.g., "#FF000040" for semi-transparent red)
            border_color: Border line color
            border_width: Border line width
            persistent: If True, overlay survives zoom changes (redrawn automatically)
        """
        from PySide6.QtWidgets import QGraphicsPolygonItem
        from PySide6.QtGui import QPolygonF

        if len(coords) < 3:
            return None

        # Store data for redraw on zoom if persistent
        if persistent:
            self._overlay_data.append({
                'type': 'polygon',
                'coords': list(coords),
                'params': {'color': color, 'border_color': border_color, 'border_width': border_width}
            })

        # Convert lat/lon to pixel coordinates
        points = []
        for lat, lon in coords:
            px, py = lat_lon_to_pixel(lat, lon, self.zoom)
            points.append(QPointF(px, py))

        # Create polygon
        polygon = QPolygonF(points)
        item = QGraphicsPolygonItem(polygon)

        # Set colors
        item.setBrush(QBrush(QColor(color)))
        item.setPen(QPen(QColor(border_color), border_width))
        item.setZValue(50)  # Below marker, above tiles

        self.scene.addItem(item)
        self.overlay_items.append(item)
        return item

    def add_overlay_line(self, coords: list, color: str = "#FF0000", width: float = 2.0,
                        persistent: bool = True):
        """
        Add a line overlay to the map.

        Args:
            coords: List of (lat, lon) tuples defining the line path
            color: Line color
            width: Line width
            persistent: If True, overlay survives zoom changes (redrawn automatically)
        """
        from PySide6.QtWidgets import QGraphicsPathItem
        from PySide6.QtGui import QPainterPath

        if len(coords) < 2:
            return None

        # Store data for redraw on zoom if persistent
        if persistent:
            self._overlay_data.append({
                'type': 'line',
                'coords': list(coords),
                'params': {'color': color, 'width': width}
            })

        # Convert to pixel coordinates
        path = QPainterPath()
        first = True
        for lat, lon in coords:
            px, py = lat_lon_to_pixel(lat, lon, self.zoom)
            if first:
                path.moveTo(px, py)
                first = False
            else:
                path.lineTo(px, py)

        item = QGraphicsPathItem(path)
        item.setPen(QPen(QColor(color), width))
        item.setZValue(50)

        self.scene.addItem(item)
        self.overlay_items.append(item)
        return item

    def clear_overlays(self):
        """Remove all overlay items and stored data from the map."""
        for item in self.overlay_items:
            self.scene.removeItem(item)
        self.overlay_items.clear()
        self._overlay_data.clear()

    def _clear_overlay_items(self):
        """Remove overlay graphics items but keep stored data for redraw."""
        for item in self.overlay_items:
            self.scene.removeItem(item)
        self.overlay_items.clear()

    def _update_overlays(self):
        """Redraw persistent overlays at new zoom level."""
        if not self._overlay_data:
            return

        # Remove old graphics items
        self._clear_overlay_items()

        # Redraw each overlay from stored geo-coordinate data
        for data in self._overlay_data:
            if data['type'] == 'polygon':
                self.add_overlay_polygon(
                    data['coords'],
                    persistent=False,  # Don't re-store, already in _overlay_data
                    **data['params']
                )
            elif data['type'] == 'line':
                self.add_overlay_line(
                    data['coords'],
                    persistent=False,
                    **data['params']
                )

    # === Mouse Event Handlers ===

    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press - start potential drag"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._did_drag = False  # Reset drag flag
            self._drag_start_pos = event.position()  # Store original position
            self._last_mouse_pos = event.position()
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse move for panning"""
        if self._dragging:
            delta = event.position() - self._last_mouse_pos
            self._last_mouse_pos = event.position()

            # Check if this is significant movement (more than 5 pixels from start)
            total_delta = event.position() - self._drag_start_pos
            if abs(total_delta.x()) > 5 or abs(total_delta.y()) > 5:
                self._did_drag = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)

            # Only pan if actually dragging
            if self._did_drag:
                # Pan the view
                self.horizontalScrollBar().setValue(
                    int(self.horizontalScrollBar().value() - delta.x())
                )
                self.verticalScrollBar().setValue(
                    int(self.verticalScrollBar().value() - delta.y())
                )

                # Load new tiles if needed
                self._load_visible_tiles()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        """Handle mouse release - either complete drag or register click"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.setCursor(Qt.CursorShape.ArrowCursor)

            # If mouse didn't move significantly, it's a click - set marker
            if not self._did_drag:
                # Use the original press position for accuracy
                scene_pos = self.mapToScene(self._drag_start_pos.toPoint())
                lat, lon = pixel_to_lat_lon(scene_pos.x(), scene_pos.y(), self.zoom)

                # Clamp to valid range
                lat = max(-85.0, min(85.0, lat))
                lon = max(-180.0, min(180.0, lon))

                self.set_marker(lat, lon)
                self.location_clicked.emit(lat, lon)

            self._did_drag = False

        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        """Handle mouse wheel for zooming"""
        # Get position before zoom
        old_pos = self.mapToScene(event.position().toPoint())

        # Calculate new zoom
        delta = event.angleDelta().y()
        if delta > 0:
            new_zoom = self.zoom + 1
        else:
            new_zoom = self.zoom - 1

        # Apply zoom
        old_zoom = self.zoom
        self.set_zoom(new_zoom)

        # If zoom changed, adjust view to keep mouse position stable
        if self.zoom != old_zoom:
            # Recalculate the scene position at new zoom
            scale_factor = 2 ** (self.zoom - old_zoom)
            new_scene_x = old_pos.x() * scale_factor
            new_scene_y = old_pos.y() * scale_factor

            # Center on new position
            self.centerOn(new_scene_x, new_scene_y)
            self._load_visible_tiles()

    def resizeEvent(self, event):
        """Handle resize - load more tiles if needed"""
        super().resizeEvent(event)
        self._load_visible_tiles()

    def showEvent(self, event):
        """Handle show - center and load tiles"""
        super().showEvent(event)
        self._center_on_position()

    def closeEvent(self, event):
        """Cleanup on close"""
        self.tile_cache.close()
        super().closeEvent(event)

    # === Online Zoom API ===

    def is_online_zoom(self) -> bool:
        """Check if current zoom level requires online tiles"""
        cached_max = self.tile_cache.get_cached_max_zoom()
        return self.zoom > cached_max

    def is_online_enabled(self) -> bool:
        """Check if online tile fetching is enabled"""
        return self.tile_cache.is_online_enabled()

    def get_max_zoom(self) -> int:
        """Get maximum available zoom level (including online)"""
        return self.tile_cache.get_max_zoom()

    def get_cached_max_zoom(self) -> int:
        """Get maximum zoom level in local cache"""
        return self.tile_cache.get_cached_max_zoom()

class OfflineMapPanel(QWidget):
    """
    Complete map panel with controls and coordinate display.

    Combines OfflineMapWidget with:
    - Zoom controls
    - Coordinate display
    - Capital quick-select
    """

    location_selected = Signal(float, float, str, str)  # lat, lon, city, country

    def __init__(self, db_path: str = None, parent=None):
        super().__init__(parent)

        self.db_path = db_path
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """Create the panel UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        # === Top Control Bar ===
        control_bar = QHBoxLayout()
        control_bar.setSpacing(10)

        # Coordinate display
        self.coord_label = QLabel("Click map to select location")
        self.coord_label.setStyleSheet("font-family: monospace; padding: 5px;")
        control_bar.addWidget(self.coord_label)

        control_bar.addStretch()

        # Zoom buttons
        self.zoom_out_btn = QPushButton("-")
        self.zoom_out_btn.setFixedSize(30, 30)
        self.zoom_out_btn.setToolTip("Zoom out")
        control_bar.addWidget(self.zoom_out_btn)

        self.zoom_label = QLabel("Zoom: 2")
        self.zoom_label.setMinimumWidth(60)
        control_bar.addWidget(self.zoom_label)

        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.setFixedSize(30, 30)
        self.zoom_in_btn.setToolTip("Zoom in")
        control_bar.addWidget(self.zoom_in_btn)

        # Capital quick-select
        self.capital_combo = QComboBox()
        self.capital_combo.setMinimumWidth(150)
        self.capital_combo.addItem("Quick Select Capital...")
        self._populate_capitals()
        control_bar.addWidget(self.capital_combo)

        layout.addLayout(control_bar)

        # === Map Widget ===
        self.map_widget = OfflineMapWidget(self.db_path, self)
        layout.addWidget(self.map_widget, stretch=1)

    def _populate_capitals(self):
        """Populate capital dropdown from WORLD_CAPITALS"""
        try:
            from tools.capitals_data import WORLD_CAPITALS

            # Sort capitals alphabetically
            sorted_capitals = sorted(WORLD_CAPITALS.keys())
            for capital in sorted_capitals:
                self.capital_combo.addItem(capital)
        except ImportError:
            print("Warning: Could not import WORLD_CAPITALS")

    def _connect_signals(self):
        """Wire up signal connections"""
        self.map_widget.location_clicked.connect(self._on_location_clicked)
        self.zoom_in_btn.clicked.connect(self._zoom_in)
        self.zoom_out_btn.clicked.connect(self._zoom_out)
        self.capital_combo.currentTextChanged.connect(self._on_capital_selected)

    def _on_location_clicked(self, lat: float, lon: float):
        """Handle map click"""
        # Update coordinate display
        lat_dir = "N" if lat >= 0 else "S"
        lon_dir = "E" if lon >= 0 else "W"
        self.coord_label.setText(
            f"{abs(lat):.6f}° {lat_dir}, {abs(lon):.6f}° {lon_dir}"
        )

        # Try reverse geocoding
        city, country = self._reverse_geocode(lat, lon)

        # Emit signal
        self.location_selected.emit(lat, lon, city, country)

    def _reverse_geocode(self, lat: float, lon: float) -> Tuple[str, str]:
        """
        Get city/country from coordinates.

        Uses geopy if available, otherwise finds nearest capital.
        """
        city = ""
        country = ""

        # Try geopy first
        try:
            from geopy.geocoders import Nominatim
            from geopy.exc import GeocoderTimedOut, GeocoderServiceError

            geolocator = Nominatim(user_agent="Varuna360/1.0 (Vedic Astrology App; astrologielorris@gmail.com)", timeout=3)
            location = geolocator.reverse(f"{lat}, {lon}", language="en")

            if location and location.raw:
                address = location.raw.get('address', {})
                city = (address.get('city') or
                       address.get('town') or
                       address.get('village') or
                       address.get('municipality') or "")
                country = address.get('country', '')
                return city, country
        except Exception:
            pass  # Fall back to capitals

        # Fallback: find nearest capital
        try:
            from tools.capitals_data import WORLD_CAPITALS

            best_dist = float('inf')
            best_capital = None

            for name, data in WORLD_CAPITALS.items():
                cap_lat = data.get('latitude', 0)
                cap_lon = data.get('longitude', 0)

                # Simple distance calculation
                dist = (lat - cap_lat) ** 2 + (lon - cap_lon) ** 2
                if dist < best_dist:
                    best_dist = dist
                    best_capital = (name, data.get('country', ''))

            if best_capital:
                city, country = best_capital
        except ImportError:
            pass

        return city, country

    def _zoom_in(self):
        """Increase zoom level"""
        self.map_widget.set_zoom(self.map_widget.get_zoom() + 1)
        self._update_zoom_label()

    def _zoom_out(self):
        """Decrease zoom level"""
        self.map_widget.set_zoom(self.map_widget.get_zoom() - 1)
        self._update_zoom_label()

    def _update_zoom_label(self):
        """Update zoom display"""
        self.zoom_label.setText(f"Zoom: {self.map_widget.get_zoom()}")

    def _on_capital_selected(self, capital_name: str):
        """Handle capital dropdown selection"""
        if capital_name == "Quick Select Capital..." or not capital_name:
            return

        try:
            from tools.capitals_data import WORLD_CAPITALS

            if capital_name in WORLD_CAPITALS:
                data = WORLD_CAPITALS[capital_name]
                lat = data.get('latitude', 0)
                lon = data.get('longitude', 0)
                country = data.get('country', '')

                # Set marker and center map
                self.map_widget.set_marker(lat, lon)
                self.map_widget.set_position(lat, lon)
                self.map_widget.set_zoom(5)  # City level
                self._update_zoom_label()

                # Update display
                lat_dir = "N" if lat >= 0 else "S"
                lon_dir = "E" if lon >= 0 else "W"
                self.coord_label.setText(
                    f"{abs(lat):.6f}° {lat_dir}, {abs(lon):.6f}° {lon_dir}"
                )

                # Emit signal
                self.location_selected.emit(lat, lon, capital_name, country)

                # Reset combo to placeholder
                self.capital_combo.blockSignals(True)
                self.capital_combo.setCurrentIndex(0)
                self.capital_combo.blockSignals(False)
        except ImportError:
            pass

    # === Public API ===

    def set_marker(self, lat: float, lon: float):
        """Set marker and center map"""
        self.map_widget.set_marker(lat, lon)
        self.map_widget.set_position(lat, lon)

        # Update display
        lat_dir = "N" if lat >= 0 else "S"
        lon_dir = "E" if lon >= 0 else "W"
        self.coord_label.setText(
            f"{abs(lat):.6f}° {lat_dir}, {abs(lon):.6f}° {lon_dir}"
        )

    def get_marker_position(self) -> Optional[Tuple[float, float]]:
        """Get current marker position or None"""
        if self.map_widget.marker_lat is not None:
            return (self.map_widget.marker_lat, self.map_widget.marker_lon)
        return None
