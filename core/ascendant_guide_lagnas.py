# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The Ascendant Guide read from several lagnas (the AI's get_ascendant_guide,
SPEC-ASG-001): the natal Ascendant first, then houses counted from the Sun
(Surya Lagna), the Moon (Chandra Lagna) or a Chara karaka.

Each lagna is the South Indian guide's own model (``core.ascendant_guide.
frame_guide``) on the view's own projection with the ascendant moved to that
planet's sector, exactly what the 1-12 selector does. A new lagna is one
``LAGNAS`` row, one ``_lagna_planet`` line and its wording in
ascendant_guide.json ``lagnas``. Kept out of ``core/ascendant_guide.py`` on
purpose: that module is under the SI architecture budget.
"""
from core.aditya_mode import ADITYA_NAMES
from core.ascendant_guide import frame_guide, teaching_data
from core.retinue_constants import sign_lord

# Dhata (sector 1) is the foundation from every lagna; Tvasta (sector 7, always
# the 7th from Dhata) is the relationship with that foundation, the self facing
# others. Sector N is the Nth Aditya in every zodiac (SPEC-ZOD-001), so their
# lords, Mars and Venus, hold in the three frames.
AXIS = (('foundation', 0), ('relationship', 6))

# The South Indian view's planets (apps/widgets/chart_view.SouthIndianView.PLANET_NAMES).
PLANET_NAMES = ('Sun', 'Moon', 'Mars', 'Mercury', 'Jupiter', 'Venus', 'Saturn',
                'Rahu', 'Ketu', 'Uranus', 'Neptune', 'Pluto')
KARAKA_CODES = ('AK', 'AmK', 'BK', 'MK', 'PiK', 'GK', 'DK')
LAGNAS = ('asc', 'sun', 'moon') + tuple('karaka:' + c for c in KARAKA_CODES)
MODES = ('aditya', 'tropical_classic', 'sidereal')


class GuideNotApplicable(ValueError):
    """The chart is outside the guide's frames (``error_type`` for invoke)."""
    error_type = 'not_applicable'


def applies(mode, use_western_names):
    """The guide reads Aditya sectors under the Aditya names, in any of the
    three zodiacs (SPEC-ZOD-001: sector N is the Nth Aditya in every zodiac)."""
    return mode in MODES and not use_western_names


def lagna_wording(key):
    """Lorris's wording for one lagna (``asc``, ``sun``, ``moon``,
    ``karaka:<code>``), placeholders removed: an entry still marked
    ``copy_pending`` gives nothing (it never reaches a reader)."""
    data = teaching_data().get('lagnas', {})
    if key.startswith('karaka:'):
        entry = data.get('karaka', {}).get(key.split(':', 1)[1], {})
    else:
        entry = data.get(key, {})
    if not entry or entry.get('copy_pending'):
        return {}
    return {k: v for k, v in entry.items() if k != 'copy_pending'}


def natal_snapshot(chart, mode, use_western_names, show_outer=True, ascendant=None):
    """The South Indian render snapshot of the D1 chart, built by the view's
    own projection (no Qt), optionally re-anchored on ``ascendant``."""
    from core.south_indian_render_data import RenderProjection
    rashi = chart.rashi()
    projection = RenderProjection()
    projection.configure(chart, rashi.cusps(), rashi.planets(), None, mode,
                         use_western_names, 'en', ascendant)
    return projection.snapshot(PLANET_NAMES, show_outer)


def _lagna_planet(key, karakas):
    if key == 'sun':
        return 'Sun', None
    if key == 'moon':
        return 'Moon', None
    if key.startswith('karaka:'):
        code = key.split(':', 1)[1]
        row = next((r for r in karakas if r['code'] == code), None)
        if row is None:
            raise GuideNotApplicable(f'no {code} in this chart')
        return row['planet'], row
    return None, None


def lagna_guides(chart, mode, use_western_names, lagnas=('asc',), show_outer=True):
    """The guide from each requested lagna, natal Ascendant first."""
    if not applies(mode, use_western_names):
        raise GuideNotApplicable(
            'The Ascendant Guide reads the Aditya sectors under the Aditya names; this '
            'chart uses the Western sign names, so the guide does not apply to it.')
    unknown = [k for k in lagnas if k not in LAGNAS]
    if unknown:
        raise GuideNotApplicable(f'unknown lagna(s) {unknown}; choose from {list(LAGNAS)}')
    order = ['asc'] + [k for k in dict.fromkeys(lagnas) if k != 'asc']
    base = natal_snapshot(chart, mode, use_western_names, show_outer)
    birth = base.ascendant_sign
    cells = {p.name: p.cell for p in base.planets}
    karakas = []
    if any(k.startswith('karaka:') for k in order):
        from core.capabilities.karakas_aspects import karaka_rows
        karakas = karaka_rows(chart, mode)
    out = []
    for key in order:
        planet, karaka = _lagna_planet(key, karakas)
        if planet is not None and planet not in cells:
            raise GuideNotApplicable(f'{planet} is not in this chart')
        sector = birth if planet is None else cells[planet]
        snap = base if sector == birth else natal_snapshot(
            chart, mode, use_western_names, show_outer, sector)
        model = frame_guide(snap, birth)
        out.append(_lagna_entry(key, planet, karaka, model, snap))
    return {'applies': True, 'mode': mode, 'varga': 1, 'birth_sector': birth + 1,
            'lagnas': out, 'available_lagnas': list(LAGNAS),
            'source': teaching_data()['source']}


def _lagna_entry(key, planet, karaka, model, snap):
    words = lagna_wording(key)
    lagna = model['sign']
    placements = {p: h for p, h in model['placements']}
    houses = []
    for n in range(1, 13):
        sector = (lagna + n - 1) % 12
        row = {'house': n, 'sector': sector + 1, 'aditya': ADITYA_NAMES[sector],
               'planets': [p.name for p in snap.planets if p.cell == sector],
               **_lord(sector, placements, lagna)}
        meaning = (words.get('houses') or {}).get(str(n))
        if meaning:
            row['meaning'] = meaning
        houses.append(row)
    entry = {'lagna': key, 'name': words.get('name') or _default_name(key, planet, karaka),
             'planet': planet,
             'sector': lagna + 1, 'aditya': model['aditya'],
             'birth_ascendant_sector': model['birth'],
             'teaching': ({'title': model['teaching']['title'], 'text': model['teaching']['text']}
                          if model['teaching'] else None),
             'occupants': list(model['occupants']),
             'occupant_purposes': {p: model['purposes'][p] for p in model['occupants']
                                   if p in model['purposes']},
             'houses': houses,
             'placements': placements,
             'foundation_house': model['foundation']}
    for name, sector in AXIS:
        row = houses[(sector - lagna) % 12]
        entry[name] = {**row, 'meaning': axis_wording(name)}
    if karaka is not None:
        entry['karaka'] = {'code': karaka['code'], 'role': karaka['karaka']}
    if words.get('meaning'):
        entry['meaning'] = words['meaning']
    return entry


def _lord(sector, placements, lagna):
    """The sector's lord and where it stands, counted from this lagna."""
    lord = sign_lord(sector)
    house = placements.get(lord)
    out = {'lord': lord, 'lord_house': house}
    if house is not None:
        s = (lagna + house - 1) % 12
        out.update(lord_sector=s + 1, lord_aditya=ADITYA_NAMES[s])
    return out


def axis_wording(name):
    """Lorris's wording for the foundation (Dhata) or the relationship (Tvasta)."""
    return teaching_data().get('axis', {}).get(name, {}).get('meaning', '')


def _default_name(key, planet, karaka):
    if karaka is not None:          # "DK - Dara (Spouse)" -> "Darakaraka"
        return karaka['karaka'].split(' - ', 1)[-1].split()[0] + 'karaka'
    return planet or key
