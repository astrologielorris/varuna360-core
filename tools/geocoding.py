"""
Geocoding utilities — pure functions using geopy + timezonefinder.

Extracted from AI_tools/chart_generation/web_birth_data_to_chtk.py during
the browser-code cleanup (Phase 2). No selenium dependency.
"""

from datetime import datetime
from typing import Dict, Optional, Any

from core.time_utils import format_offset, resolve_total_offset


# Known city coordinates for common birthplaces (fallback when API fails)
KNOWN_CITIES = {
    "bay city": {"latitude": 43.5945, "longitude": -83.8889},  # Michigan, USA
    "new york": {"latitude": 40.7128, "longitude": -74.0060},
    "los angeles": {"latitude": 34.0522, "longitude": -118.2437},
    "london": {"latitude": 51.5074, "longitude": -0.1278},
    "paris": {"latitude": 48.8566, "longitude": 2.3522},
    "tokyo": {"latitude": 35.6762, "longitude": 139.6503},
    "mumbai": {"latitude": 19.0760, "longitude": 72.8777},
    "sydney": {"latitude": -33.8688, "longitude": 151.2093},
    "chicago": {"latitude": 41.8781, "longitude": -87.6298},
    "houston": {"latitude": 29.7604, "longitude": -95.3698},
    "dallas": {"latitude": 32.7767, "longitude": -96.7970},
    "seattle": {"latitude": 47.6062, "longitude": -122.3321},
    "boston": {"latitude": 42.3601, "longitude": -71.0589},
    "atlanta": {"latitude": 33.7490, "longitude": -84.3880},
    "berlin": {"latitude": 52.5200, "longitude": 13.4050},
    "rome": {"latitude": 41.9028, "longitude": 12.4964},
    "madrid": {"latitude": 40.4168, "longitude": -3.7038},
    "beijing": {"latitude": 39.9042, "longitude": 116.4074},
    "shanghai": {"latitude": 31.2304, "longitude": 121.4737},
    "hong kong": {"latitude": 22.3193, "longitude": 114.1694},
    "singapore": {"latitude": 1.3521, "longitude": 103.8198},
    "toronto": {"latitude": 43.6532, "longitude": -79.3832},
    "melbourne": {"latitude": -37.8136, "longitude": 144.9631},
    "jamshedpur": {"latitude": 22.8046, "longitude": 86.2029},  # Jharkhand (formerly Bihar)
    "passaic": {"latitude": 40.8568, "longitude": -74.1285},  # New Jersey
    "shillong": {"latitude": 25.5788, "longitude": 91.8933},  # Meghalaya, India
    "warren": {"latitude": 41.2375, "longitude": -80.8184},  # Ohio
    "london, ontario": {"latitude": 42.9849, "longitude": -81.2453},  # Canada (not UK!)
}


def _get_known_city_coords(city: str, country: str = "") -> Optional[Dict[str, float]]:
    """Fallback lookup for known cities. Also checks city name before comma."""
    city_lower = city.lower().strip()
    if city_lower in KNOWN_CITIES:
        return KNOWN_CITIES[city_lower]
    # Try just the city name before comma (handles "Jamshedpur, Bihar" -> "jamshedpur")
    city_base = city_lower.split(',')[0].strip()
    if city_base != city_lower and city_base in KNOWN_CITIES:
        return KNOWN_CITIES[city_base]
    return None


def geocode_city(city: str, country: str = "") -> Optional[Dict[str, float]]:
    """
    Get coordinates for a city using geopy.

    Args:
        city: City name
        country: Country name (optional, improves accuracy)

    Returns:
        Dict with 'latitude' and 'longitude', or None if not found
    """
    # Check known cities first (handles cases where geopy returns wrong location)
    known = _get_known_city_coords(city, country)
    if known:
        return known

    # SPEC-MAP-001 D-13: this used to run an unconditional `time.sleep(1.2)`
    # before every request — including when the answer came from the table
    # above and no request was made at all, and including when the last real
    # call was minutes ago. Nominatim's policy is one request per second
    # BETWEEN ACTUAL REQUESTS, which is what geocode_service enforces; in
    # practice the wait is now zero. That sleep was over half of the ~2 s
    # Add Chart delay.
    try:
        from core.geocode_service import forward

        query = f"{city}, {country}" if country else city
        result = forward(query)
        if result is not None:
            return {'latitude': result.lat, 'longitude': result.lon}

        # Fallback: city alone (a wrong or unknown region should not sink it).
        if country:
            result = forward(city)
            if result is not None:
                return {'latitude': result.lat, 'longitude': result.lon}

    except ImportError:
        print("[WARN] geopy not installed. Run: pip install geopy")
    except Exception as e:
        # Try fallback to known cities
        coords = _get_known_city_coords(city, country)
        if coords:
            return coords
        print(f"[WARN] Geocoding error for {city}: {e}")

    return None


def get_timezone_for_coordinates(lat: float, lon: float, birth_date: datetime = None) -> Dict[str, Any]:
    """
    Get timezone offset for coordinates using timezonefinder.

    Separates DST from standard offset; CHTK format needs them stored separately.

    Args:
        lat: Latitude
        lon: Longitude
        birth_date: Birth date, REQUIRED for historical timezone accuracy
                    (raises ValueError if None)

    Returns:
        Dict with 'offset' (standard UTC string like "-06:00") and 'dst_active' (bool)
    """
    # Same logic lives in browser_tools/web_birth_data_to_chtk.py and
    # browser_tools/web_birth_data.py (no dedup this RPI); keep all three in sync.
    # Raise BEFORE the try block: inside it, the except Exception below would
    # swallow the ValueError into the longitude fallback.
    if birth_date is None:
        raise ValueError("birth_date is required for historical timezone accuracy")
    try:
        # SPEC-MAP-001 INV-7: the shared finder. Constructing one here cost
        # 788 ms, and resolve_location() then constructed a SECOND one for the
        # same coordinate — 1.6 s of pure waste per chart.
        from core.tz_finder import timezone_at

        tz_name = timezone_at(lat, lon)

        if tz_name:
            # Canonical IANA-rules DST detection (SPEC-TZ-001,
            # decompose-from-total): returned std + flag equals the pytz
            # TOTAL offset at the birth instant. Replaces the old ZoneInfo
            # dst() + 1h idiom, which picked the DST reading on fold-overlap
            # instants; the resolver takes the standard-time reading.
            # longitude gives city-accurate LMT for pre-standardization dates.
            std_hours, dst_flag = resolve_total_offset(
                tz_name, birth_date.year, birth_date.month, birth_date.day,
                birth_date.hour, birth_date.minute, longitude=lon)

            total_minutes = int(round(std_hours * 60))
            sign = 1 if total_minutes >= 0 else -1
            am = abs(total_minutes)
            offset_str = format_offset(sign * (am // 60), sign * (am % 60))

            return {'offset': offset_str, 'dst_active': bool(dst_flag)}

    except ImportError:
        print("[WARN] timezonefinder not installed. Run: pip install timezonefinder")
    except Exception as e:
        print(f"[WARN] Timezone lookup error: {e}")

    # Fallback: estimate from longitude
    print(f"[TZ-CHECK] Timezone lookup failed; falling back to longitude estimate "
          f"for lat={lat}, lon={lon} (no DST, whole-hour offset)")
    estimated_hours = round(lon / 15)
    sign = '+' if estimated_hours >= 0 else '-'
    return {'offset': f"{sign}{abs(estimated_hours):02d}:00", 'dst_active': False}
