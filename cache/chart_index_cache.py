"""
Chart Index Cache - Pre-calculates and caches all planetary positions for CHTK files
Enables fast searching and filtering of chart database by any celestial body
"""

import os
import json
import glob
from datetime import datetime
from core.chtk_reader import CHTKReader
from core.chart_factory import build_chart_from_params
import re

# v3: added per-planet tropical longitude ({planet}_lon) so search can compute
# the sign in the user's current zodiac mode instead of relabeling a fixed system.
CACHE_VERSION = 3

# Filterable bodies: entry key (lowercase) -> libaditya planet name.
FILTER_BODIES = {
    'ascendant': 'Ascendant', 'sun': 'Sun', 'moon': 'Moon', 'mars': 'Mars',
    'mercury': 'Mercury', 'jupiter': 'Jupiter', 'venus': 'Venus',
    'saturn': 'Saturn', 'rahu': 'Rahu', 'ketu': 'Ketu', 'uranus': 'Uranus',
    'neptune': 'Neptune', 'pluto': 'Pluto',
}


def sign_index_in_mode(longitude, mode='aditya', ayanamsa_offset=0.0):
    """Sign index (0-11) of a tropical longitude in the given zodiac mode.

    Mirrors how the chart wheel labels signs, so search matches the display.
    """
    from core.aditya_mode import (
        get_sign_index_tropical, get_sign_index_aditya, get_sign_index_sidereal,
    )
    if mode == 'aditya':
        return get_sign_index_aditya(longitude)
    if mode == 'sidereal':
        return get_sign_index_sidereal(longitude, ayanamsa_offset)
    return get_sign_index_tropical(longitude)  # tropical_classic


def query_sign_index(sign_name):
    """Map a query sign name (Aditya or Western) to its ordinal index 0-11.

    The relabel is ordinal-preserving (Dhata=Aries=#1), so the ordinal index is
    the same in any naming and equals the target sign index in the current mode.
    """
    from core.aditya_mode import ADITYA_NAMES, TROPICAL_NAMES
    if sign_name in ADITYA_NAMES:
        return ADITYA_NAMES.index(sign_name)
    if sign_name in TROPICAL_NAMES:
        return TROPICAL_NAMES.index(sign_name)
    return None


class ChartIndexCache:
    """
    Manages a cached index of CHTK chart files with pre-calculated planetary positions.
    """

    def __init__(self, cache_file=None):
        """
        Initialize the cache.

        Args:
            cache_file: Path to cache JSON file. Defaults to OS-specific cache file.
        """
        if cache_file is None:
            import platform
            from state.user_data import get_user_data_dir, get_default_data_dir
            data_dir = get_user_data_dir() or get_default_data_dir()
            base_dir = os.path.join(str(data_dir), 'cache')
            os.makedirs(base_dir, exist_ok=True)
            if platform.system() == 'Windows':
                cache_file = os.path.join(base_dir, '.chart_index_cache.json')
            else:
                cache_file = os.path.join(base_dir, '.chart_index_cache_linux.json')

        self.cache_file = cache_file
        self.index = {}  # {filepath: {name, ascendant, sun, moon, mars, ..., city, country, ...}}
        self.chtk_reader = CHTKReader()
        self._load_cache()

    def _load_cache(self):
        """Load existing cache from disk if available."""
        if not os.path.exists(self.cache_file):
            import shutil
            # Check old locations: repo root, then old cache/ subdir next to source
            source_dir = os.path.dirname(os.path.abspath(__file__))
            repo_root = os.path.dirname(source_dir)
            candidates = [
                os.path.join(repo_root, os.path.basename(self.cache_file)),
                os.path.join(source_dir, os.path.basename(self.cache_file)),
            ]
            for old_path in candidates:
                if old_path != self.cache_file and os.path.exists(old_path):
                    try:
                        shutil.copy2(old_path, self.cache_file)
                        print(f"[CACHE] Migrated old cache from {old_path}")
                    except OSError as e:
                        print(f"[CACHE] Migration failed from {old_path}: {e}")
                    break

        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.index = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"[WARNING] Could not load cache: {e}")
                self.index = {}

    def _save_cache(self):
        """Save cache to disk."""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.index, f, indent=2, ensure_ascii=False)
        except IOError as e:
            print(f"[ERROR] Could not save cache: {e}")

    def _get_file_modified_time(self, filepath):
        """Get file modification time as ISO string."""
        try:
            mtime = os.path.getmtime(filepath)
            return datetime.fromtimestamp(mtime).isoformat()
        except OSError:
            return None

    def _make_skip_entry(self, filepath, chtk_data, reason):
        """
        Create a placeholder entry for files that can't be fully processed.
        This prevents re-processing on every startup.

        Args:
            filepath: Path to CHTK file
            chtk_data: Parsed CHTK data (may be incomplete)
            reason: Why this file was skipped

        Returns:
            dict with basic info and skip marker
        """
        folder_name = os.path.basename(os.path.dirname(filepath))
        return {
            'name': chtk_data.get('name', os.path.splitext(os.path.basename(filepath))[0]) if chtk_data else os.path.splitext(os.path.basename(filepath))[0],
            'ascendant': '?',
            'sun': '?',
            'moon': '?',
            'mars': '?',
            'mercury': '?',
            'jupiter': '?',
            'venus': '?',
            'saturn': '?',
            'rahu': '?',
            'ketu': '?',
            'uranus': '?',
            'neptune': '?',
            'pluto': '?',
            'city': chtk_data.get('city', '') if chtk_data else '',
            'country': chtk_data.get('country', '') if chtk_data else '',
            'birth_date': '?',
            'birth_time': '?',
            'file_modified': self._get_file_modified_time(filepath),
            'folder': folder_name,
            'filepath': filepath,
            'ascendant_trimsamsa': '?', 'ascendant_hora': '?',
            'sun_trimsamsa': '?', 'sun_hora': '?',
            'moon_trimsamsa': '?', 'moon_hora': '?',
            'mars_trimsamsa': '?', 'mars_hora': '?',
            'mercury_trimsamsa': '?', 'mercury_hora': '?',
            'jupiter_trimsamsa': '?', 'jupiter_hora': '?',
            'venus_trimsamsa': '?', 'venus_hora': '?',
            'saturn_trimsamsa': '?', 'saturn_hora': '?',
            'rahu_trimsamsa': '?', 'rahu_hora': '?',
            'ketu_trimsamsa': '?', 'ketu_hora': '?',
            '_cache_version': CACHE_VERSION,
            '_skipped': True,
            '_skip_reason': reason
        }

    def _calculate_chart_data(self, filepath):
        """
        Read CHTK file and calculate planetary positions.

        Args:
            filepath: Path to CHTK file

        Returns:
            dict with chart data or None if failed
        """
        try:
            chtk_data = self.chtk_reader.read_chtk_file(filepath)
            if not chtk_data:
                return self._make_skip_entry(filepath, None, "empty or invalid CHTK file")

            # Extract birth data
            year = chtk_data.get('year', 0)
            month = chtk_data.get('month', 0)
            day = chtk_data.get('day', 0)
            hour = chtk_data.get('hour', 0)
            minute = chtk_data.get('minute', 0)
            second = chtk_data.get('second', 0)

            # === VALIDATION: Skip files with unsupported data ===
            # BCE years (negative) not supported by Python datetime
            if year < 1:
                return self._make_skip_entry(filepath, chtk_data, f"BCE year ({year})")

            # Clamp invalid time values
            hour = max(0, min(23, hour))
            minute = max(0, min(59, minute))
            second = max(0, min(59, second))

            # Validate month
            if month < 1 or month > 12:
                return self._make_skip_entry(filepath, chtk_data, f"invalid month ({month})")

            # Validate day for month (handle edge cases)
            import calendar
            max_day = calendar.monthrange(year, month)[1]
            if day < 1 or day > max_day:
                return self._make_skip_entry(filepath, chtk_data, f"invalid day ({day}) for month {month}")

            # Get coordinates
            coords = chtk_data.get('coordinates', {})
            lat = coords.get('latitude', 0.0)
            lon = coords.get('longitude', 0.0)

            # Handle timezone - convert CHTK offset to UTC
            chtk_tz = chtk_data.get('timezone', '+00:00:00')
            time_change_flag = chtk_data.get('time_change_flag', 0)

            # Parse and invert timezone (CHTK uses opposite convention)
            match = re.match(r'([+-])(\d{1,2}):(\d{2}):(\d{2})', str(chtk_tz))
            if match:
                sign, hours, minutes, seconds = match.groups()
                offset_hours = int(hours) if sign == '-' else -int(hours)
                offset_minutes = int(minutes) if sign == '-' else -int(minutes)

                # Apply DST if flagged
                if time_change_flag == 1:
                    offset_hours += 1
            else:
                offset_hours = 0
                offset_minutes = 0

            # Convert to UTC
            from datetime import timedelta
            local_dt = datetime(year, month, day, hour, minute, second)
            utc_dt = local_dt - timedelta(hours=offset_hours, minutes=offset_minutes)

            from libaditya import swe
            hour_dec = utc_dt.hour + utc_dt.minute / 60.0 + utc_dt.second / 3600.0
            jd = swe.julday(utc_dt.year, utc_dt.month, utc_dt.day, hour_dec)
            _chart = build_chart_from_params(jd=jd, lat=lat, lon=lon, mode="aditya", ayanamsa=1)

            from core.chart_helpers import get_planet_sign_name, get_planet_in_sign_longitude, get_planet_decimal_degrees

            ascendant = get_planet_sign_name(_chart, 'Ascendant')
            sun = get_planet_sign_name(_chart, 'Sun')
            moon = get_planet_sign_name(_chart, 'Moon')
            mars = get_planet_sign_name(_chart, 'Mars')
            mercury = get_planet_sign_name(_chart, 'Mercury')
            jupiter = get_planet_sign_name(_chart, 'Jupiter')
            venus = get_planet_sign_name(_chart, 'Venus')
            saturn = get_planet_sign_name(_chart, 'Saturn')
            rahu = get_planet_sign_name(_chart, 'Rahu')
            ketu = get_planet_sign_name(_chart, 'Ketu')
            uranus = get_planet_sign_name(_chart, 'Uranus')
            neptune = get_planet_sign_name(_chart, 'Neptune')
            pluto = get_planet_sign_name(_chart, 'Pluto')

            # Tropical ecliptic longitudes for mode-aware sign matching at search
            # time (the cached sign names above are Aditya Circle only).
            lon_fields = {
                f'{key}_lon': round(get_planet_decimal_degrees(_chart, pname), 6)
                for key, pname in FILTER_BODIES.items()
            }

            from AI_tools.AI_main_function.retinue import get_retinue, RETINUE_PLANETS
            retinue_fields = {}
            for planet in RETINUE_PLANETS:
                sign_name = get_planet_sign_name(_chart, planet)
                if sign_name and sign_name != '?':
                    degree = get_planet_in_sign_longitude(_chart, planet)
                    r = get_retinue(sign_name, degree)
                    if r:
                        retinue_fields[f'{planet.lower()}_trimsamsa'] = r['trimsamsa']['being_name']
                        retinue_fields[f'{planet.lower()}_hora'] = r['hora']['being_name']
                    else:
                        retinue_fields[f'{planet.lower()}_trimsamsa'] = '?'
                        retinue_fields[f'{planet.lower()}_hora'] = '?'
                else:
                    retinue_fields[f'{planet.lower()}_trimsamsa'] = '?'
                    retinue_fields[f'{planet.lower()}_hora'] = '?'

            folder_name = os.path.basename(os.path.dirname(filepath))

            birth_date = f"{year:04d}-{month:02d}-{day:02d}"
            birth_time = f"{hour:02d}:{minute:02d}"

            entry = {
                'name': chtk_data.get('name', os.path.splitext(os.path.basename(filepath))[0]),
                'ascendant': ascendant,
                'sun': sun,
                'moon': moon,
                'mars': mars,
                'mercury': mercury,
                'jupiter': jupiter,
                'venus': venus,
                'saturn': saturn,
                'rahu': rahu,
                'ketu': ketu,
                'uranus': uranus,
                'neptune': neptune,
                'pluto': pluto,
                'city': chtk_data.get('city', ''),
                'country': chtk_data.get('country', ''),
                'birth_date': birth_date,
                'birth_time': birth_time,
                'file_modified': self._get_file_modified_time(filepath),
                'folder': folder_name,
                'filepath': filepath,
                '_cache_version': CACHE_VERSION,
            }
            entry.update(retinue_fields)
            entry.update(lon_fields)
            return entry

        except Exception as e:
            # Silently create skip entry - these will be cached to avoid re-processing
            # Common reasons: BCE dates, invalid times, empty files
            return self._make_skip_entry(filepath, None, str(e))

    def build_index(self, folder_paths, progress_callback=None):
        """
        Build/rebuild the index for all CHTK files in given folders.

        Args:
            folder_paths: List of folder paths to scan
            progress_callback: Optional callback(current, total, filepath, cached, stats) for progress updates
                - cached: True if using cached data, False if calculated fresh
                - stats: dict with 'cached_count' and 'calculated_count'

        Returns:
            dict: The complete index
        """
        # Folders to exclude from indexing (deleted files, temporary data)
        excluded_folders = {'trash', '.trash', 'to_migrate'}

        # Find all CHTK files (deduplicate in case of overlapping paths)
        all_files = []
        seen_files = set()
        for folder in folder_paths:
            if folder and os.path.exists(folder):
                files = glob.glob(os.path.join(folder, "**", "*.chtk"), recursive=True)
                for f in files:
                    norm_f = os.path.normpath(f)
                    # Skip files inside excluded folders
                    path_parts = norm_f.replace('\\', '/').split('/')
                    if any(part.lower() in excluded_folders for part in path_parts):
                        continue
                    if norm_f not in seen_files:
                        seen_files.add(norm_f)
                        all_files.append(f)

        total = len(all_files)
        new_index = {}
        stats = {'cached_count': 0, 'calculated_count': 0, 'skipped_count': 0}

        for i, filepath in enumerate(all_files):
            # Check if we have a valid cached entry
            file_modified = self._get_file_modified_time(filepath)
            cached = self.index.get(filepath)

            if (cached
                    and cached.get('file_modified') == file_modified
                    and cached.get('_cache_version', 0) >= CACHE_VERSION):
                new_index[filepath] = cached
                is_cached = True
                stats['cached_count'] += 1
                if cached.get('_skipped'):
                    stats['skipped_count'] += 1
            else:
                # Calculate fresh data
                chart_data = self._calculate_chart_data(filepath)
                if chart_data:
                    new_index[filepath] = chart_data
                    if chart_data.get('_skipped'):
                        stats['skipped_count'] += 1
                is_cached = False
                stats['calculated_count'] += 1

            # Progress callback with cache info
            if progress_callback:
                progress_callback(i + 1, total, filepath, is_cached, stats)

            # Periodic save so progress survives app close mid-build
            if (i + 1) % 500 == 0:
                self.index = new_index
                self._save_cache()

        self.index = new_index
        self._save_cache()
        return self.index

    def get_all_entries(self):
        """Get all cached entries as a list."""
        return list(self.index.values())

    def search(self, query='', sort_by='name', group_by=None, reverse=False,
               mode='aditya', ayanamsa_offset=0.0):
        """
        Search and filter the index.

        Args:
            query: Search string (matches name, city, country) or planet filters like "sun:Dhata"
            sort_by: Sort key ('name', 'file_modified', 'country', 'birth_date')
            group_by: Group key (None, 'folder', 'ascendant', 'sun', 'moon')
            reverse: Sort in descending order (default False = ascending)

        Returns:
            list: Filtered and sorted entries (or grouped dict if group_by is set)
        """
        entries = list(self.index.values())

        # Filter by query
        if query:
            import re

            # Parse planet filters (e.g., "sun:Dhata", "ascendant:Varuna")
            planet_filters = {}
            filter_pattern = r'\b(\w+):(\w+)\b'

            # Extract planet:sign filters from query
            for match in re.finditer(filter_pattern, query):
                planet_key = match.group(1).lower()
                sign_name = match.group(2)

                valid_planets = {
                    'ascendant', 'sun', 'moon', 'mars', 'mercury',
                    'jupiter', 'venus', 'saturn', 'rahu', 'ketu',
                    'uranus', 'neptune', 'pluto'
                }
                valid_being_keys = {
                    'ascendant_being', 'sun_being', 'moon_being',
                    'mars_being', 'mercury_being', 'jupiter_being',
                    'venus_being', 'saturn_being', 'rahu_being', 'ketu_being'
                }

                if planet_key in valid_planets or planet_key in valid_being_keys:
                    planet_filters[planet_key] = sign_name

            # Get text search part (remove planet:sign filters)
            text_query = re.sub(filter_pattern, '', query).strip()
            text_query = text_query.strip('.,;:!?()[]{}"\'-/')
            query_lower = text_query.lower() if text_query else ''

            # Filter entries
            filtered_entries = []
            for e in entries:
                # Check text search (name, city, country)
                text_match = (
                    not query_lower or
                    query_lower in e.get('name', '').lower()
                    or query_lower in e.get('city', '').lower()
                    or query_lower in e.get('country', '').lower()
                )

                planet_match = True
                for planet_key, sign_name in planet_filters.items():
                    if planet_key.endswith('_being'):
                        base = planet_key.replace('_being', '')
                        tri_val = e.get(f'{base}_trimsamsa', '')
                        hora_val = e.get(f'{base}_hora', '')
                        if sign_name not in (tri_val, hora_val):
                            planet_match = False
                            break
                    else:
                        # Mode-aware match: compute the planet's sign in the
                        # CURRENT zodiac mode from its stored tropical longitude,
                        # and compare to the query's ordinal sign index. This makes
                        # search agree with the chart display in every mode.
                        lon = e.get(f'{planet_key}_lon')
                        target_idx = query_sign_index(sign_name)
                        if lon is not None and target_idx is not None:
                            if sign_index_in_mode(lon, mode, ayanamsa_offset) != target_idx:
                                planet_match = False
                                break
                        else:
                            # Legacy fallback (pre-v3 entry or unresolved name):
                            # exact match on the stored Aditya Circle name.
                            if e.get(planet_key, '') != sign_name:
                                planet_match = False
                                break

                if text_match and planet_match:
                    filtered_entries.append(e)

            entries = filtered_entries

        # Aditya zodiac order (Dhata = 1st sign, Parjanya = 12th sign)
        ADITYA_ORDER = [
            'Dhata', 'Aryama', 'Mitra', 'Varuna', 'Indra', 'Vivasvan',
            'Tvasta', 'Vishnu', 'Amzu', 'Bhaga', 'Pusha', 'Parjanya'
        ]

        def aditya_sort_key(sign_name):
            """Return sort index for Aditya sign (0-11), or 99 for unknown."""
            try:
                return ADITYA_ORDER.index(sign_name)
            except ValueError:
                return 99  # Unknown signs sort last

        # Sort
        sort_keys = {
            'name': lambda e: e.get('name', '').lower(),
            'file_modified': lambda e: e.get('file_modified', '') or '',
            'country': lambda e: (e.get('country', '').lower(), e.get('name', '').lower()),
            'birth_date': lambda e: (e.get('birth_date', '') or '', e.get('birth_time', '') or '', e.get('name', '').lower()),
            'ascendant': lambda e: (aditya_sort_key(e.get('ascendant', '')), e.get('name', '').lower()),
            'sun': lambda e: (aditya_sort_key(e.get('sun', '')), e.get('name', '').lower()),
            'moon': lambda e: (aditya_sort_key(e.get('moon', '')), e.get('name', '').lower()),
            'city': lambda e: (e.get('city', '').lower(), e.get('name', '').lower()),
        }
        sort_key = sort_keys.get(sort_by, sort_keys['name'])
        entries.sort(key=sort_key, reverse=reverse)

        # Group if requested
        if group_by:
            grouped = {}
            for entry in entries:
                group_value = entry.get(group_by, 'Unknown')
                if group_value not in grouped:
                    grouped[group_value] = []
                grouped[group_value].append(entry)
            return grouped

        return entries

    def get_entry(self, filepath):
        """Get a single cached entry by filepath."""
        return self.index.get(filepath)

    def clear_cache(self):
        """Clear the cache completely."""
        self.index = {}
        if os.path.exists(self.cache_file):
            os.remove(self.cache_file)


# Test the module
if __name__ == "__main__":
    cache = ChartIndexCache()

    # Test with chtk_files folder
    test_folder = os.path.join(os.path.dirname(__file__), 'chtk_files')

    def progress(current, total, filepath, is_cached, stats):
        status = "✓" if is_cached else "→"
        print(f"[{current}/{total}] {status} {os.path.basename(filepath)}")

    print("Building index...")
    cache.build_index([test_folder], progress_callback=progress)

    print(f"\nIndexed {len(cache.index)} charts")

    # Test search
    results = cache.search("john")
    print(f"\nSearch for 'john': {len(results)} results")
    for r in results[:5]:
        print(f"  - {r['name']} | Asc: {r['ascendant']} | Sun: {r['sun']} | Moon: {r['moon']}")
