"""Reading facts from the exact South Indian render snapshot; no recalculation."""
import json
from functools import lru_cache
from pathlib import Path
from core.aditya_mode import ADITYA_NAMES, displayed_sign_name


@lru_cache(maxsize=1)
def teaching_data():
    return json.loads((Path(__file__).parent / 'data' / 'ascendant_guide.json').read_text())


def build_guide(snapshot, birth_sign=None):
    if not snapshot.has_chart:
        return {'notice': 'Load a chart to explore its ascendant frames.'}
    if snapshot.compass_mode:
        return {'notice': 'Reading guides are available in the Aditya chart. Compass uses a different frame.'}
    return frame_guide(snapshot, birth_sign)


def frame_guide(snapshot, birth_sign):
    asc = snapshot.ascendant_sign
    names = [displayed_sign_name(i, snapshot.aditya_mode, snapshot.use_western_names,
                                 snapshot.sign_language) for i in range(12)]
    occupants = tuple(p.name for p in snapshot.planets if p.cell == asc)
    supported = snapshot.aditya_mode == 'aditya' and snapshot.varga_code in (None, 1)
    data = teaching_data()
    teaching = data['adityas'].get(str(asc), {}) if supported else {}
    return dict(sign=asc, name=names[asc], aditya=ADITYA_NAMES[asc],
                occupants=occupants, major=tuple(p for p in occupants if p in ('Sun', 'Moon')),
                birth=asc == birth_sign, teaching=teaching,
                purposes=data['planets'] if supported else {},
                supported=supported, varga=snapshot.varga_code,
                placements=tuple((p.name, (p.cell-asc) % 12+1) for p in snapshot.planets),
                foundation=(0-asc) % 12+1,
                source=data['source'] if supported else '')
