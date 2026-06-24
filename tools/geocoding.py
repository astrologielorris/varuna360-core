"""
Geocoding utilities — pure functions using geopy + timezonefinder.

Extracted from AI_tools/chart_generation/web_birth_data_to_chtk.py during
the browser-code cleanup (Phase 2). No selenium dependency.
"""

from datetime import datetime, timedelta
from typing import Dict, Optional, Any

from core.time_utils import format_offset


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
    import time

    # Check known cities first (handles cases where geopy returns wrong location)
    known = _get_known_city_coords(city, country)
    if known:
        return known

    try:
        from geopy.geocoders import Nominatim
        from geopy.exc import GeocoderTimedOut, GeocoderServiceError

        geolocator = Nominatim(
            user_agent="Varuna360/1.0 (Vedic Astrology App; astrologielorris@gmail.com)",
            timeout=10)

        # Rate limiting: sleep before request
        time.sleep(1.2)  # Nominatim requires 1 second between requests

        # Try with country first for better accuracy
        query = f"{city}, {country}" if country else city
        location = geolocator.geocode(query)

        if location:
            return {
                'latitude': location.latitude,
                'longitude': location.longitude
            }

        # Fallback: try city only with delay
        if country:
            time.sleep(1.2)
            location = geolocator.geocode(city)
            if location:
                return {
                    'latitude': location.latitude,
                    'longitude': location.longitude
                }

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
        from timezonefinder import TimezoneFinder
        from zoneinfo import ZoneInfo

        tf = TimezoneFinder()
        tz_name = tf.timezone_at(lat=lat, lng=lon)

        if tz_name:
            tz = ZoneInfo(tz_name)
            dt_with_tz = birth_date.replace(tzinfo=tz)
            utc_offset = dt_with_tz.utcoffset()
            dst_delta = dt_with_tz.dst()

            if utc_offset is not None:
                # Deliberate change from subtracting dst_delta: std = total
                # minus 1h when DST active (decompose-from-total rule,
                # SPEC-TZ-001; differs for fractional-DST zones like Lord Howe).
                dst_active = dst_delta is not None and dst_delta.total_seconds() > 0
                if dst_active:
                    standard_offset = utc_offset - timedelta(hours=1)
                else:
                    standard_offset = utc_offset

                total_sec = int(standard_offset.total_seconds())
                sign = 1 if total_sec >= 0 else -1
                a = abs(total_sec)
                offset_str = format_offset(sign * (a // 3600), sign * ((a % 3600) // 60))

                return {'offset': offset_str, 'dst_active': dst_active}

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
