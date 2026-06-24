# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Transit Utilities - Shared transit chart calculation logic.

Extracted from transit_panel.py so both the Transit tab and the
"Now" button in the main chart tab can reuse the same code.

No GUI dependencies - pure calculation + geolocation.
"""

from datetime import datetime, timezone
from typing import Optional, Tuple

# Chart-Everywhere Issue 14: get_all_planets_data import removed —
# transit chart now built via core.chart_factory.

# Module-level cache for geolocation (avoids repeated API calls)
_cached_location: Optional[Tuple[float, float]] = None
_cached_location_name: Optional[str] = None
_cached_iana_timezone: Optional[str] = None


def set_location(lat: float, lon: float, name: str = ""):
    """
    Override the cached location (e.g., from map selection).

    Clears the IANA timezone cache so it's re-detected for the new coordinates.

    Args:
        lat: Latitude
        lon: Longitude
        name: Display name (e.g., "New York, US")
    """
    global _cached_location, _cached_location_name, _cached_iana_timezone

    _cached_location = (float(lat), float(lon))
    _cached_location_name = name or f"({lat:.2f}, {lon:.2f})"
    _cached_iana_timezone = None  # Force re-detection for new coords


def clear_location():
    """Clear cached location so next call auto-detects via IP geolocation."""
    global _cached_location, _cached_location_name, _cached_iana_timezone
    _cached_location = None
    _cached_location_name = None
    _cached_iana_timezone = None


def get_current_location() -> Tuple[float, float]:
    """
    Get current location via IP geolocation, with caching.

    Priority:
    1. Cached location (set manually or from previous geolocation)
    2. IP geolocation via geocoder
    3. Default (0, 0) as fallback

    Returns:
        Tuple of (latitude, longitude)
    """
    global _cached_location, _cached_location_name

    if _cached_location is not None:
        return _cached_location

    try:
        import geocoder
        g = geocoder.ip('me')
        if g.ok and g.latlng:
            lat, lon = g.latlng
            city = g.city or "Unknown city"
            country = g.country or ""
            _cached_location = (float(lat), float(lon))
            _cached_location_name = f"{city}, {country}"
            return _cached_location
        else:
            print(f"[TRANSIT] Geolocation failed: {g.status}")
    except ImportError:
        print("[TRANSIT] geocoder not installed, trying stdlib fallback")
    except Exception as e:
        print(f"[TRANSIT] Geolocation error: {e}")

    # Stdlib fallback: ipinfo.io returns JSON with no extra dependencies
    try:
        import urllib.request, json as _json
        with urllib.request.urlopen("https://ipinfo.io/json", timeout=5) as resp:
            data = _json.loads(resp.read().decode())
        loc = data.get("loc", "")
        if loc and "," in loc:
            lat, lon = [float(x) for x in loc.split(",")]
            city = data.get("city", "Unknown city")
            country = data.get("country", "")
            _cached_location = (lat, lon)
            _cached_location_name = f"{city}, {country}"
            return _cached_location
    except Exception as e:
        print(f"[TRANSIT] Stdlib fallback geolocation error: {e}")

    print("[TRANSIT] WARNING: Could not detect location! Using default (0,0)")
    return (0.0, 0.0)


def get_current_location_name() -> str:
    """Get the cached location name for display."""
    global _cached_location_name
    return _cached_location_name or "Unknown location"


def get_iana_timezone(lat: float, lon: float) -> str:
    """
    Get IANA timezone string from coordinates using timezonefinder.

    Uses cache only if coordinates match the cached location.

    Args:
        lat: Latitude
        lon: Longitude

    Returns:
        IANA timezone string (e.g., 'Indian/Reunion', 'Europe/Paris'), or 'UTC' on failure.
    """
    global _cached_iana_timezone

    if _cached_iana_timezone is not None:
        return _cached_iana_timezone

    try:
        from timezonefinder import TimezoneFinder
        tf = TimezoneFinder()
        tz_str = tf.timezone_at(lat=lat, lng=lon)
        if tz_str:
            _cached_iana_timezone = tz_str
            return tz_str
    except ImportError:
        print("[TRANSIT] timezonefinder not installed")
    except Exception as e:
        print(f"[TRANSIT] Timezone detection error: {e}")

    return "UTC"


def calculate_transit_now(lat: Optional[float] = None, lon: Optional[float] = None,
                          mode: str = "aditya", ayanamsa: Optional[int] = None,
                          target_dt: Optional[datetime] = None) -> Optional[Tuple]:
    """Calculate planetary positions for a given moment (default: now).

    Args:
        lat, lon: Observer location. If None, uses get_current_location().
        mode: Zodiac mode — "aditya", "tropical_classic", or "sidereal".
        ayanamsa: Ayanamsa ID. Required — no default to prevent Bug #7 regression.
        target_dt: Compute transit for this UTC datetime instead of now.

    Returns:
        (Chart, iana_timezone_str) tuple, or None on error.
    """
    if ayanamsa is None:
        raise ValueError(
            "calculate_transit_now() requires explicit ayanamsa — "
            "pass from gui.chart_sidereal_ayanamsa_id or chart.context.ayanamsa"
        )
    try:
        from libaditya import swe
        from core.chart_factory import build_chart_from_params

        dt = target_dt if target_dt is not None else datetime.now(timezone.utc)

        if lat is None or lon is None:
            lat, lon = get_current_location()

        iana_tz = get_iana_timezone(lat, lon)

        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo(iana_tz)
        dt_local = dt.astimezone(local_tz)
        utc_off = dt_local.utcoffset().total_seconds() / 3600.0

        hour_decimal = dt.hour + dt.minute / 60.0 + dt.second / 3600.0
        jd = swe.julday(dt.year, dt.month, dt.day, hour_decimal)
        chart = build_chart_from_params(jd=jd, lat=lat, lon=lon, mode=mode,
                                        ayanamsa=ayanamsa, utcoffset=utc_off)

        return chart, iana_tz

    except Exception as e:
        print(f"[TRANSIT] Error calculating transit: {e}")
        import traceback
        traceback.print_exc()
        return None
