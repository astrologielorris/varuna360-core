"""Shared ecliptic ayanamsa offset matching libaditya chart coordinates."""
from functools import lru_cache


@lru_cache(maxsize=65536)
def birth_ayanamsa_offset(jd, ayanamsa_id):
    """Engine ecliptic sign offset at this birth, independent of active chart."""
    from libaditya import swe, utils
    if ayanamsa_id == 999:
        return 0.0
    if ayanamsa_id in (99, 100):
        return -utils.vedanga_ecliptic_aval(jd)
    swe.set_sid_mode(36 if ayanamsa_id == 98 else ayanamsa_id)
    if ayanamsa_id == 97:
        utils.set_swe_true_sidereal_ayanamsa()
    # Include nutation, matching the apparent tropical longitudes in the index
    # and Swiss FLG_SIDEREAL positions (mean ayanamsa differs by arcseconds).
    return swe.get_ayanamsa_ex_ut(jd, 0)[1]



@lru_cache(maxsize=65536)
def birth_sidereal_ascendant_index(jd, lat, lon, ayanamsa_id):
    """Use the exact house engine; special sidereal modes are not scalar shifts.

    The cached Ascendant-only probe avoids building a full Chart or reading the
    source file when filtering, sorting, grouping, and rendering the same birth.
    """
    from core.chart_helpers import ascendant_probe
    return ascendant_probe(jd, lat, lon, 'sidereal', ayanamsa_id)[0]


@lru_cache(maxsize=65536)
def birth_projected_planet_index(jd, ayanamsa_id, planet_name):
    """Exact individual planet for Swiss non-scalar ecliptic projections.

    Instantiate the engine's actual planet class, including its true-node
    convention, without paying for a full Chart and its derived calculations.
    """
    from libaditya.objects import planets
    from libaditya.objects.context import EphContext, Circle
    from libaditya.objects.julian_day import JulianDay
    from libaditya import constants
    ctx = EphContext(timeJD=JulianDay(jd), circle=Circle.ZODIAC,
                     sysflg=constants.SID, ayanamsa=ayanamsa_id, amsha=1,
                     signize=True, toround=(True, 3), sign_names='zodiac')
    planet = getattr(planets, planet_name)(context=ctx)
    return planet.amsha_sign_index()
