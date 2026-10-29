"""Canonical nakshatra description records (Core and Lite).

Shared by the nakshatra info dialog (Core wheel sector click, Pro tab,
Antikythera) and the Pro summary renderers. The data file
``core/data/nakshatra_data.json`` holds the descriptions by Ernst Wilhelm and
Michael Reed, used with permission of both authors; its ``meta`` block carries
the credit line every surface that shows the text must display.
"""
from functools import lru_cache
import json
from pathlib import Path

from libaditya.constants import names

_DATA_PATH = Path(__file__).resolve().parent / 'data' / 'nakshatra_data.json'
_IDENTITIES = tuple(names['eng']['nakshatras'])
GUNAS = ('Rajasic', 'Tamasic', 'Sattvic')

# Shown wherever the descriptions are displayed (also in the data file's meta).
CREDIT_LINE = ('Nakshatra descriptions by Ernst Wilhelm and Michael Reed, '
               'used with permission.')


@lru_cache(maxsize=1)
def _load_document():
    try:
        doc = json.loads(_DATA_PATH.read_text(encoding='utf-8'))
        rows = doc.get('nakshatras') if isinstance(doc, dict) else None
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError('Expected {"meta": ..., "nakshatras": [records]}')
        return doc
    except (OSError, ValueError) as exc:
        print(f'[NAK_DIALOG] Error loading nakshatra data: {exc}')
        return {'meta': {}, 'nakshatras': []}


def load_nakshatra_data():
    """Return the ordered records; missing data is explicitly unavailable ([])."""
    return _load_document()['nakshatras']


def nakshatra_data_meta():
    """The data file's meta block (authors, credit, permission)."""
    return dict(_load_document().get('meta') or {})


def credit_line():
    """The credit line to display with the descriptions."""
    return nakshatra_data_meta().get('credit') or CREDIT_LINE


def detail_index(identity):
    """Resolve source row by canonical astronomical identity, not display order."""
    if identity not in _IDENTITIES:
        return None
    number = _IDENTITIES.index(identity) + 1
    return next((i for i, row in enumerate(load_nakshatra_data())
                 if row.get('astronomical_index') == number), None)


def guna_triplet(identity):
    index = detail_index(identity)
    if index is None:
        return None
    value = load_nakshatra_data()[index].get('esoteric', {}).get('gunas', '')
    parts = tuple(part.strip() for part in value.split('-'))
    return parts if len(parts) == 3 and all(part in GUNAS for part in parts) else None


# Captions and source paths for the one reusable outer summary ring.
PROPERTY_FIELDS = {
    'deity': ('Deity', ('summary', 'deity')),
    'emissary': ('Emissary', ('summary', 'emissary')),
    'body_part': ('Body parts', ('summary', 'body_part')),
    'yoni': ('Yoni', ('summary', 'yoni')),
    'symbol': ('Symbol', ('summary', 'symbol')),
    'place': ('Place', ('summary', 'place')),
    'number_of_stars': ('Stars', ('summary', 'number_of_stars')),
    'dosha': ('Dosha', ('esoteric', 'dosha')),
    'kingdom': ('Kingdom', ('esoteric', 'kingdom')),
    'gana': ('Gana', ('esoteric', 'gana')),
    'nature': ('Nature', ('esoteric', 'nature')),
    'gender': ('Gender', ('esoteric', 'gender')),
    'activity': ('Activity', ('esoteric', 'activity')),
    'caste': ('Caste', ('esoteric', 'caste')),
    'facing': ('Facing', ('esoteric', 'facing')),
    'kbn': ('KBN', ('esoteric', 'kbn')),
    'trimurthi': ('Trimurti', ('esoteric', 'trimurthi')),
    'primary_motivation': ('Motivation', ('esoteric', 'primary_motivation')),
}
PROPERTY_OPTIONS = (('none', 'Outer ring: Off'), ('gunas', 'Gunas')) + tuple(
    (key, caption) for key, (caption, _) in PROPERTY_FIELDS.items())


def property_value(identity, mode):
    """Preserve source strings and annotated lists; never substitute display order."""
    index = detail_index(identity)
    if index is None:
        return None
    _, (block, key) = PROPERTY_FIELDS[mode]
    value = load_nakshatra_data()[index].get(block, {}).get(key)
    if isinstance(value, list):
        return ' / '.join(str(part).strip() for part in value if str(part).strip()) or None
    return str(value).strip() if value is not None and str(value).strip() else None


def property_label(identity, mode):
    # The source also supplies a concise English nature classification.
    # Keep the full esoteric wording in the tooltip and details dialog.
    index = detail_index(identity)
    if mode == 'nature' and index is not None:
        short = load_nakshatra_data()[index].get('detail', {}).get('classification', {}).get('nature')
        if short:
            return short
    return property_value(identity, mode)
