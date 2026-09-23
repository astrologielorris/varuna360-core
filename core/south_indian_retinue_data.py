"""Qt-free retinue adapter; source objects are read only."""
from core.south_indian_retinue import from_object

def retinue_records(planets, cusps, varga, anchors, names, show_outer):
    from core.south_indian_retinue import from_object
    result = []
    omissions = []
    for name in names:
        if not show_outer and name in {'Uranus','Neptune','Pluto'}:
            continue
        try:
            obj = planets[name]
            result.append(from_object(name, obj, varga, anchors.get(name)))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            omissions.append(f'{name}: {exc}')
    _retinue_ascendant(cusps, varga, result, omissions, anchors)
    return tuple(result), tuple(omissions)

def _retinue_ascendant(cusps, varga, result, omissions, anchors):
    if cusps:
        try:
            obj = cusps[1]
            result.append(from_object('Ascendant', obj, varga, anchors.get('Ascendant')))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            omissions.append(f'Ascendant: {exc}')
