"""
Web birth data extraction: Wikidata + DuckDuckGo + TZ helpers.

Moved to browser_tools/ for Lite-First access.
"""

import json
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

from core.time_utils import format_offset


# =============================================================================
# NAME MATCHING (shared by all search sources)
# =============================================================================

def _normalize_name(name: str) -> str:
    """Strip diacriticals and lowercase: 'Faltskog' -> 'faltskog'."""
    nfkd = unicodedata.normalize('NFKD', name)
    return ''.join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def names_match(searched: str, found: str) -> bool:
    """Check if names are similar enough (handles diacriticals, hyphens, partial matches)."""
    s = _normalize_name(searched).replace('-', ' ')
    f = _normalize_name(found).replace('-', ' ')
    if s == f:
        return True
    if s in f or f in s:
        return True
    s_parts = s.split()
    f_parts = f.split()
    if len(s_parts) >= 2 and len(f_parts) >= 2:
        if s_parts[0] == f_parts[0] and s_parts[-1] == f_parts[-1]:
            return True
    return False


# =============================================================================
# CONSTANTS
# =============================================================================

MONTHS = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'may': 5, 'june': 6, 'july': 7, 'august': 8,
    'september': 9, 'october': 10, 'november': 11, 'december': 12
}

WIKIDATA_BIRTH_DATE = "P569"
WIKIDATA_BIRTH_PLACE = "P19"
WIKIDATA_COUNTRY = "P17"

USER_AGENT = "Varuna360/1.0 (Vedic Astrology App; astrologielorris@gmail.com)"


# =============================================================================
# TIMEZONE CORRECTIONS DATABASE
# =============================================================================

_tz_corrections_cache = None

def _load_tz_corrections() -> List[Dict]:
    """Load timezone corrections database (cached)."""
    global _tz_corrections_cache
    if _tz_corrections_cache is not None:
        return _tz_corrections_cache

    corrections_path = Path(__file__).parent.parent / "correction_tables" / "tz_corrections.json"
    if corrections_path.exists():
        try:
            with open(corrections_path, 'r') as f:
                data = json.load(f)
            _tz_corrections_cache = data.get("corrections", [])
        except Exception:
            _tz_corrections_cache = []
    else:
        _tz_corrections_cache = []
    return _tz_corrections_cache


def check_tz_correction(city: str, country: str, year: int, month: int, day: int) -> Optional[Dict[str, Any]]:
    """Check if a timezone correction exists for this city+country+date.

    Returns {'offset': '-06:00', 'dst_active': False} if found, else None.
    """
    corrections = _load_tz_corrections()
    city_lower = city.lower()

    for entry in corrections:
        if (entry["year"] == year and entry["month"] == month and entry["day"] == day
                and entry["city"].lower() in city_lower
                and entry["country"].lower() == country.lower()):
            return {"offset": entry["offset"], "dst_active": entry.get("dst_active", False)}
    return None


# =============================================================================
# GEOCODING
# =============================================================================

KNOWN_CITIES = {
    "bay city": {"latitude": 43.5945, "longitude": -83.8889},
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
    "jamshedpur": {"latitude": 22.8046, "longitude": 86.2029},
    "passaic": {"latitude": 40.8568, "longitude": -74.1285},
    "shillong": {"latitude": 25.5788, "longitude": 91.8933},
    "warren": {"latitude": 41.2375, "longitude": -80.8184},
    "london, ontario": {"latitude": 42.9849, "longitude": -81.2453},
}


def _get_known_city_coords(city: str, country: str = "") -> Optional[Dict[str, float]]:
    """Fallback lookup for known cities."""
    city_lower = city.lower().strip()
    if city_lower in KNOWN_CITIES:
        return KNOWN_CITIES[city_lower]
    city_base = city_lower.split(',')[0].strip()
    if city_base != city_lower and city_base in KNOWN_CITIES:
        return KNOWN_CITIES[city_base]
    return None


def geocode_city(city: str, country: str = "") -> Optional[Dict[str, float]]:
    """Get coordinates for a city using geopy."""
    import time

    known = _get_known_city_coords(city, country)
    if known:
        return known

    try:
        from geopy.geocoders import Nominatim
        from geopy.exc import GeocoderTimedOut, GeocoderServiceError

        geolocator = Nominatim(user_agent=USER_AGENT, timeout=10)

        time.sleep(1.2)

        query = f"{city}, {country}" if country else city
        location = geolocator.geocode(query)

        if location:
            return {
                'latitude': location.latitude,
                'longitude': location.longitude
            }

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
        coords = _get_known_city_coords(city, country)
        if coords:
            return coords
        print(f"[WARN] Geocoding error for {city}: {e}")

    return None


def get_timezone_for_coordinates(lat: float, lon: float, birth_date: datetime = None) -> Dict[str, Any]:
    """Get timezone offset for coordinates using timezonefinder.

    Separates DST from standard offset for CHTK format.
    birth_date is REQUIRED for historical timezone accuracy
    (raises ValueError if None).
    """
    # Same logic lives in tools/geocoding.py and
    # browser_tools/web_birth_data_to_chtk.py (no dedup this RPI); keep
    # all three in sync.
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


# =============================================================================
# WIKIPEDIA/WIKIDATA API
# =============================================================================

def search_wikidata(name: str, verbose: bool = True) -> Optional[Dict[str, Any]]:
    """Search Wikidata for birth information (P569 birth date, P19 birth place)."""
    import requests

    def log(msg):
        if verbose:
            print(f"[Wikidata] {msg}")

    try:
        log(f"Searching for '{name}'...")
        headers = {"User-Agent": USER_AGENT}

        search_url = "https://www.wikidata.org/w/api.php"
        search_params = {
            "action": "wbsearchentities",
            "search": name,
            "language": "en",
            "type": "item",
            "limit": 5,
            "format": "json"
        }

        response = requests.get(search_url, params=search_params, headers=headers, timeout=15)
        response.raise_for_status()
        search_data = response.json()

        if not search_data.get("search"):
            log(f"No results found")
            return None

        entity_id = None
        entity_label = None

        for result in search_data["search"]:
            candidate_id = result.get("id")
            candidate_label = result.get("label", name)

            log(f"Checking {candidate_label}...")

            entity_url = f"https://www.wikidata.org/wiki/Special:EntityData/{candidate_id}.json"
            entity_response = requests.get(entity_url, headers=headers, timeout=15)
            entity_response.raise_for_status()
            entity_data = entity_response.json()

            entities = entity_data.get("entities", {})
            if candidate_id in entities:
                claims = entities[candidate_id].get("claims", {})
                if WIKIDATA_BIRTH_DATE in claims:
                    entity_id = candidate_id
                    entity_label = candidate_label
                    break

        if not entity_id:
            log(f"No person with birth date found")
            return None

        log(f"Found: {entity_label} ({entity_id})")

        entity_url = f"https://www.wikidata.org/wiki/Special:EntityData/{entity_id}.json"
        entity_response = requests.get(entity_url, headers=headers, timeout=15)
        entity_response.raise_for_status()
        entity_data = entity_response.json()

        entities = entity_data.get("entities", {})
        entity = entities.get(entity_id, {})
        claims = entity.get("claims", {})

        birth_date_info = None
        if WIKIDATA_BIRTH_DATE in claims:
            birth_claim = claims[WIKIDATA_BIRTH_DATE][0]
            mainsnak = birth_claim.get("mainsnak", {})
            datavalue = mainsnak.get("datavalue", {})
            if datavalue.get("type") == "time":
                time_value = datavalue.get("value", {}).get("time", "")
                birth_date_info = _parse_wikidata_date(time_value)

        if not birth_date_info:
            log(f"Could not parse birth date")
            return None

        birth_city = "Unknown"
        birth_country = "Unknown"

        if WIKIDATA_BIRTH_PLACE in claims:
            place_claim = claims[WIKIDATA_BIRTH_PLACE][0]
            place_id = place_claim.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")

            if place_id:
                log(f"Looking up birth place...")
                place_data = _get_wikidata_place_info(place_id, headers)
                if place_data:
                    birth_city = place_data.get("city", "Unknown")
                    birth_country = place_data.get("country", "Unknown")

        if not names_match(name, entity_label):
            log(f"Name mismatch: searched '{name}' but found '{entity_label}' - rejecting")
            return None

        result = {
            "name": entity_label,
            "year": birth_date_info["year"],
            "month": birth_date_info["month"],
            "day": birth_date_info["day"],
            "hour": 12,
            "minute": 0,
            "second": 0,
            "city": birth_city,
            "country": birth_country,
            "hasBirthTime": False,
            "hasPartialDate": birth_date_info.get("partial_date", False),
            "source": "Wikidata",
            "wikidata_id": entity_id,
        }

        if birth_date_info.get("partial_date"):
            log(f"Extracted birth data (partial date - year only)")
        else:
            log(f"Successfully extracted birth data")

        return result

    except Exception as e:
        log(f"Error: {e}")

    return None


def _parse_wikidata_date(time_str: str) -> Optional[Dict]:
    """Parse Wikidata time format: +1958-08-16T00:00:00Z"""
    match = re.match(r'([+-])(\d+)-(\d{2})-(\d{2})', time_str)
    if match:
        sign, year, month, day = match.groups()
        year_int = int(year)
        if sign == '-':
            year_int = -year_int

        month_int = int(month)
        day_int = int(day)
        partial_date = False

        if month_int == 0:
            month_int = 7
            day_int = 1
            partial_date = True
        elif day_int == 0:
            day_int = 15
            partial_date = True

        return {
            "year": year_int,
            "month": month_int,
            "day": day_int,
            "partial_date": partial_date
        }
    return None


def _get_wikidata_place_info(place_id: str, headers: dict) -> Optional[Dict]:
    """Get city and country names from a Wikidata place entity."""
    import requests

    try:
        url = f"https://www.wikidata.org/wiki/Special:EntityData/{place_id}.json"
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        entities = data.get("entities", {})
        entity = entities.get(place_id, {})

        labels = entity.get("labels", {})
        city_name = labels.get("en", {}).get("value") or labels.get("fr", {}).get("value") or "Unknown"

        country_name = "Unknown"
        claims = entity.get("claims", {})
        if WIKIDATA_COUNTRY in claims:
            country_claim = claims[WIKIDATA_COUNTRY][0]
            country_id = country_claim.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
            if country_id:
                country_name = _get_wikidata_label(country_id, headers)

        return {"city": city_name, "country": country_name}

    except Exception:
        return None


def _get_wikidata_label(entity_id: str, headers: dict) -> str:
    """Get the English label for a Wikidata entity."""
    import requests

    try:
        url = f"https://www.wikidata.org/wiki/Special:EntityData/{entity_id}.json"
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        entities = data.get("entities", {})
        if entity_id in entities:
            labels = entities[entity_id].get("labels", {})
            return labels.get("en", {}).get("value") or labels.get("fr", {}).get("value") or "Unknown"
    except Exception:
        pass

    return "Unknown"


# =============================================================================
# DUCKDUCKGO API
# =============================================================================

def search_duckduckgo(name: str, verbose: bool = True) -> Optional[Dict[str, Any]]:
    """Search DuckDuckGo Instant Answers API for birth information (FREE, no API key)."""
    import requests

    def log(msg):
        if verbose:
            print(f"[DuckDuckGo] {msg}")

    try:
        log(f"Searching for '{name}'...")

        url = "https://api.duckduckgo.com/"
        params = {
            "q": name,
            "format": "json",
            "no_html": "1"
        }
        headers = {"User-Agent": USER_AGENT}

        response = requests.get(url, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()

        if data.get("Type") != "A":
            log(f"No result found (Type={data.get('Type')})")
            return None

        infobox = data.get("Infobox", {})
        if not infobox:
            log(f"No infobox data")
            return None

        content = infobox.get("content", [])
        born_str = None
        entity_name = data.get("Heading", name)

        for item in content:
            label = item.get("label", "").lower()
            value = item.get("value", "")

            if label == "born" and isinstance(value, str):
                born_str = value
                break

        if not born_str:
            log(f"No birth date in infobox")
            return None

        log(f"Found birth info: {born_str[:60]}...")

        birth_data = _parse_duckduckgo_born_string(born_str)

        if not birth_data:
            log(f"Could not parse birth date")
            return None

        if not names_match(name, entity_name):
            log(f"Name mismatch: searched '{name}' but found '{entity_name}' - rejecting")
            return None

        result = {
            "name": entity_name,
            "year": birth_data["year"],
            "month": birth_data["month"],
            "day": birth_data["day"],
            "hour": 12,
            "minute": 0,
            "second": 0,
            "city": birth_data.get("city", "Unknown"),
            "country": birth_data.get("country", "Unknown"),
            "hasBirthTime": False,
            "hasPartialDate": False,
            "source": "DuckDuckGo",
        }

        log(f"Successfully extracted birth data")
        return result

    except Exception as e:
        log(f"Error: {e}")

    return None


def _parse_duckduckgo_born_string(born_str: str) -> Optional[Dict]:
    """Parse DuckDuckGo 'Born' string format."""
    date_pattern = r'(' + '|'.join(MONTHS.keys()) + r')\s+(\d{1,2}),?\s+(\d{4})'
    match = re.search(date_pattern, born_str.lower())

    if not match:
        alt_pattern = r'(\d{1,2})\s+(' + '|'.join(MONTHS.keys()) + r'),?\s+(\d{4})'
        match = re.search(alt_pattern, born_str.lower())
        if match:
            day, month_name, year = match.groups()
            month = MONTHS.get(month_name, 1)
        else:
            return None
    else:
        month_name, day, year = match.groups()
        month = MONTHS.get(month_name, 1)

    location_match = re.search(r'\d{4},?\s*(.+)$', born_str)
    city = "Unknown"
    country = "Unknown"

    if location_match:
        location = location_match.group(1)
        parts = [p.strip() for p in location.split(',')]
        if len(parts) >= 1:
            city = parts[0]
        if len(parts) >= 2:
            country = parts[-1]
            if country.upper() in ["U.S.", "US", "USA", "U.S.A.", "UNITED STATES"]:
                country = "USA"

    return {
        "year": int(year),
        "month": month,
        "day": int(day),
        "city": city,
        "country": country
    }


# =============================================================================
# MAIN EXTRACTION LOGIC
# =============================================================================

def extract_birth_data(
    name: str,
    source: str = "auto",
    verbose: bool = True,
    visible: bool = False
) -> Optional[Dict[str, Any]]:
    """Extract birth data from web sources.

    source="auto" chains: Wikidata -> DuckDuckGo.
    """
    result = None

    if source == "auto":
        if verbose:
            print(f"[AUTO] Trying Wikidata...")
        result = search_wikidata(name, verbose)
        if result:
            if verbose:
                print(f"[AUTO] Wikidata succeeded")
        else:
            if verbose:
                print(f"[AUTO] Wikidata failed, trying DuckDuckGo...")
            result = search_duckduckgo(name, verbose)
            if result:
                if verbose:
                    print(f"[AUTO] DuckDuckGo succeeded")
            else:
                if verbose:
                    print(f"[AUTO] All sources failed")
    elif source == "wikipedia":
        result = search_wikidata(name, verbose)
    elif source == "duckduckgo":
        result = search_duckduckgo(name, verbose)
    else:
        print(f"[ERROR] Unknown source: {source}")
        return None

    if not result:
        return None

    # Add coordinates via geocoding
    city = result.get("city", "Unknown")
    country = result.get("country", "Unknown")

    if city != "Unknown":
        if verbose:
            print(f"[Geocode] Looking up coordinates for {city}, {country}...")

        coords = geocode_city(city, country)
        if coords:
            result["latitude"] = coords["latitude"]
            result["longitude"] = coords["longitude"]

            birth_dt = datetime(result["year"], result["month"], result["day"])
            correction = check_tz_correction(city, country, result["year"], result["month"], result["day"])
            if correction:
                result["timezone"] = correction['offset']
                result["dst_active"] = correction['dst_active']
                if verbose:
                    print(f"[Geocode] Found: {coords['latitude']:.4f}, {coords['longitude']:.4f} (TZ: {correction['offset']} [corrected])")
            else:
                tz_info = get_timezone_for_coordinates(coords["latitude"], coords["longitude"], birth_dt)
                result["timezone"] = tz_info['offset']
                result["dst_active"] = tz_info['dst_active']
                dst_label = " DST" if tz_info['dst_active'] else ""
                if verbose:
                    print(f"[Geocode] Found: {coords['latitude']:.4f}, {coords['longitude']:.4f} (TZ: {tz_info['offset']}{dst_label})")
        else:
            result["latitude"] = 0.0
            result["longitude"] = 0.0
            result["timezone"] = "+00:00"
            if verbose:
                print(f"[Geocode] Could not find coordinates, using defaults")
    else:
        result["latitude"] = 0.0
        result["longitude"] = 0.0
        result["timezone"] = "+00:00"

    return result
