"""Qt-free South Indian projection, using an explicitly injected Compass provider."""
from dataclasses import dataclass
from core.aditya_mode import displayed_sign_name, get_sign_index_aditya

@dataclass(frozen=True)
class PlanetRenderRecord:
    name: str
    cell: int
    degree: float
    payload: tuple
    house: int | None
    sky_label: str | None

@dataclass(frozen=True)
class RenderSnapshot:
    source_identity: int
    generation: int
    varga_code: int | None
    has_chart: bool
    ascendant_sign: int
    ascendant_degrees: tuple
    ascendant_override: int | None
    compass_mode: bool
    location_cell: int | None
    location_house: int | None
    aditya_mode: str
    use_western_names: bool
    sign_language: str
    planets: tuple
    cusps: tuple
    show_planet_names: bool

class RenderProjection:
    def __init__(self, frame_provider):
        self.generation = 0
        self.frame_provider = frame_provider
        self._chart = self._cusps = self._planets = None
        self._varga_code = None
        self._use_western_names = False
        self._aditya_mode = 'aditya'
        self.sign_language = 'en'
        self.ascendant_override = None
        self.compass_mode = False
        self._compass_armc = self._compass_eps = self._compass_jd = self._location_cell = None

    def configure(self, chart, cusps, planets, varga, mode, western, language, ascendant, compass):
        self._chart, self._cusps, self._planets = chart, cusps, planets
        self._varga_code, self._aditya_mode = varga, mode
        self._use_western_names, self.sign_language = western, language
        self.ascendant_override, self.compass_mode = ascendant, compass

    def snapshot(self, names, show_outer=True, show_names=False):
        self.generation += 1
        rows = []
        if self._planets:
            for name in names:
                if not show_outer and name in {'Uranus','Neptune','Pluto'}:
                    continue
                try:
                    obj = self._planets[name]
                    cell, degree = self._placement(obj)
                except Exception:
                    continue
                house = self._planet_house(obj) if self.compass_mode else None
                rows.append(PlanetRenderRecord(name, cell, degree,
                    tuple(self._planet_to_click_dict(name, obj).items()), house,
                    self._planet_sky_label(obj) if house is not None else None))
        return RenderSnapshot(id(self._chart), self.generation, self._varga_code, bool(self._chart), self._effective_ascendant_sign_index(),
            self.ascendant_degrees(), self.ascendant_override, self.compass_mode,
            self.location_cell, self.location_house, self._aditya_mode,
            self._use_western_names, self.sign_language, tuple(rows), self.cusp_labels(), bool(show_names))

    def cusp_labels(self):
        result = {}
        if not self._cusps:
            return ()
        try:
            for i in range(1,13):
                cusp = self._cusps[i]
                sign = cusp.sign()-1
                degree = cusp.amsha_raw_in_sign_longitude() if self._varga_code else cusp.real_in_sign_longitude()
                result.setdefault(sign,[]).append(f'C{i} {int(degree)}°')
        except Exception:
            return ()
        return tuple((sign, tuple(labels)) for sign,labels in result.items())

    def ascendant_degrees(self):
        try:
            cusp = self._cusps[1]
            degree = cusp.amsha_raw_in_sign_longitude() if self._varga_code else cusp.real_in_sign_longitude()
            return int(degree), int((degree % 1)*60)
        except Exception:
            return (0,0)

    def _effective_ascendant_sign_index(self):
        """Effective Ascendant sign index: F4 override, else cusp 1
            (classic chart_view.py:2427-2433)."""
        if self.ascendant_override is not None:
            return self.ascendant_override % 12
        if not self._cusps:
            return 0
        return self._cusps[1].sign() - 1

    def _sky_deg_min(self, planet):
        """(degrees, minutes) within the SKY sign, varga-aware (classic
            :2790-2792). Renamed from _planet_deg_min (SPEC-SIC-004 INV-6): this is
            the sky frame, used ONLY by the click payload so nobody rewires it to
            the compass degree by accident. The glyph label under a planet uses the
            placement degree instead (compass while on)."""
        risl = planet.amsha_raw_in_sign_longitude() if self._varga_code else planet.real_in_sign_longitude()
        return (int(risl), int(risl % 1 * 60))

    def _chart_jd(self):
        """The chart's UT Julian Day, or None (no chart / no time)."""
        try:
            return self._chart.context.timeJD.jd
        except Exception:
            return None

    def _compass_position(self, planet):
        """(cell, deg) of a planet in the Earth-fixed compass frame, or None
            when the chart has no jd. INV-9: the pro.core.compass_frame import lives
            ONLY here and in set_compass_mode — both compass-on paths — so the Core
            build (no pro/) never imports it. The Yamakoti ARMC and the true
            obliquity (v1.1, right ascension frame) are computed lazily and cached
            until the next update_from_chart invalidates them."""
        if self._compass_armc is None or self._compass_eps is None:
            jd = self._chart_jd()
            if jd is None:
                return None
            self._compass_armc = self.frame_provider().yamakoti_armc(jd)
            self._compass_eps = self.frame_provider().true_obliquity(jd)
            self._compass_jd = jd
        cp = self.frame_provider().compass_position(self.frame_provider().planet_right_ascension(planet, self._compass_eps, self._compass_jd), self._compass_armc)
        return (cp.cell, cp.deg)

    def _location_longitude(self):
        """The chart location's east-positive longitude, or None when the
            attribute chain is missing (INV-9: no pro import, libaditya only)."""
        try:
            return float(self._chart.context.location.longitude())
        except Exception:
            return None

    def _is_default_location(self):
        """True when the chart carries libaditya's DEFAULT Location (Yamakoti:
            lat 0, its own default longitude within 1e-3, placename 'Yamakoti'),
            treated as 'no location' (D-H5). Compared against the library's own
            default object, never the literal 165.7667 (which is 3.3e-5 off, so a
            tight comparison would never match). Defence only: no GUI path makes the
            default object (build_chart_from_params writes the chart name into
            placename)."""
        try:
            loc = self._chart.context.location
            from libaditya.objects.location import Location
            return loc.latitude() == 0 and abs(loc.longitude() - Location().longitude()) < 0.001 and (loc.placename() == 'Yamakoti')
        except Exception:
            return False

    @property
    def location_cell(self):
        """The compass cell (0-11) of the chart's OWN location, or None.

            None WITHOUT importing pro when the compass is off (INV-H8: compass_mode
            is read first). While on: None on the sign-frame fallback (no jd, D-H8),
            for a chart with no location, or for libaditya's default Yamakoti object
            (D-H5). Otherwise the cell, computed lazily on the first compass-in-effect
            draw and cached until update_from_chart / clear_chart invalidate it."""
        if not self.compass_mode:
            return None
        if self._location_cell is not None:
            return self._location_cell
        if self._chart_jd() is None:
            return None
        lon = self._location_longitude()
        if lon is None or self._is_default_location():
            return None
        self._location_cell = self.frame_provider().location_cell(lon)
        return self._location_cell

    @property
    def location_house(self):
        """The house of the location's cell (INV-H4, HOUSE_OF_ADITYA_SIGN), or
            None — 'the house we are in', emphasised on every planet label carrying
            it. None (no import) while the compass is off."""
        cell = self.location_cell
        if cell is None:
            return None
        return self.frame_provider().HOUSE_OF_ADITYA_SIGN[cell]

    def _planet_house(self, planet):
        """The planet's house (1-12) from its TROPICAL longitude by body + jd
            (INV-H1), or None without a jd or when the longitude helper refuses a
            sidereal duck (ValueError caught here so a refusal never aborts the
            card's planet loop). Never from the compass cell (INV-H2), never from
            planet.sign()."""
        jd = self._chart_jd()
        if jd is None:
            return None
        try:
            return self.frame_provider().compass_house(self.frame_provider().planet_tropical_longitude(planet, jd))
        except ValueError:
            return None

    def _planet_sky_label(self, planet):
        """The planet's zodiac sign named by ORDINAL as the Aditya-mode grid
            names it (Tvasta; Libra / Balance under Western labels), for the house
            label's tooltip (D-H7 / SPEC-SIC-005 section 3.4). NOT the tropical band
            name (Virgo) and never planet.sign_name()."""
        jd = self._chart_jd()
        lon = self.frame_provider().planet_tropical_longitude(planet, jd)
        return displayed_sign_name(get_sign_index_aditya(lon), 'aditya', self._use_western_names, self.sign_language)

    def _placement(self, planet):
        """The SINGLE (cell, deg) read for a planet (INV-6): the cell it is
            grouped into, the sort key, the lone-planet zone and the degree label
            under the glyph all come from here. Compass off (or on-but-no-jd): the
            sky sign and in-sign degree, varga-aware, exactly as before. Compass on
            with a jd: the Earth band and in-band degree."""
        if self.compass_mode:
            pos = self._compass_position(planet)
            if pos is not None:
                return pos
        varga = self._varga_code
        risl = planet.amsha_raw_in_sign_longitude() if varga else planet.real_in_sign_longitude()
        return (planet.sign() - 1, risl)

    def _planet_to_click_dict(self, planet_name, planet):
        """Classic click payload shape (chart_view.py:2794-2805). Always the
            SKY frame (sign + sky degree); while the compass is on it ADDS
            compass_cell/compass_deg so the dialog can show both frames without
            mixing them (SPEC-SIC-004 INV-6)."""
        deg, mins = self._sky_deg_min(planet)
        payload = {'sign': planet.sign_name(), 'aditya_zodiac': planet.sign_name(), 'sign_index': planet.sign() - 1, 'degrees': deg, 'minutes': mins, 'decimal_degrees': planet.ecliptic_longitude(), 'is_retrograde': planet.retrograde()}
        if self.compass_mode:
            pos = self._compass_position(planet)
            if pos is not None:
                payload['compass_cell'] = pos[0]
                payload['compass_deg'] = pos[1]
        return payload
