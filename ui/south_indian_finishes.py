# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Approved wood pigments. Appearance only; no chart calculations.

Transcribed from the approved bois-clair-patine themes.js on 2026-09-11.
Runtime resources live under img/background, never in design documentation.
Earth and Fire follow the shared wheel retinue palette; wood opacity stays local.
"""
from core.retinue_constants import TRIMSAMSA_COLORS

FINISHES = ("standard", "santal", "ash")
SIGN_DISPLAYS = ("names", "zodiac", "josh", "josh_only")
JOSH_FILES = ("dhata", "aryama", "mitra", "varuna", "indra", "vivasvan",
              "tvashta", "vishnu", "amzu", "bhaga", "pushan", "parjanya")


def normalize_finish(value):
    return value if value in FINISHES else "standard"


def normalize_sign_display(value):
    return value if value in SIGN_DISPLAYS else "zodiac"


WOOD = {'santal': {'id': 'santal',
            'label': 'Santal doux',
            'hint': 'honey beige, finely sanded',
            'wood': 'assets/wood-santal.webp',
            'room': {'bg': '#241a0e',
                     'bg2': '#2c2114',
                     'ink': '#a5947a',
                     'dim': '#6d6152',
                     'brass': '#c9a257'},
            'carve': {'lit': '#FFF8E8', 'dark': '#402A12', 'relief': 1},
            'wash': 0.07,
            'washAir': 0.08,
            'spine': 0.78,
            'ink': {'main': '#3A2810',
                    'soft': '#4C3A20',
                    'faint': '#5A4830',
                    'lip': 'rgba(255,250,236,.50)',
                    'brass': '#C9A257',
                    'asc': '#4A3306',
                    'ascSub': '#5E4512',
                    'plate': '#F7EDD6',
                    'plateInk': '#2C1D08',
                    'plateSub': '#4E3C22',
                    'marker': '#F6EBD2',
                    'focus': '#7A5A12', 'highlight': '#5A6470',  # slate: reads on honey wood
                    'title': '#46351C',
                    'titleSub': '#55452C'},
            'stain': {'Fire': {'c': TRIMSAMSA_COLORS['Fire']['bg'], 'o': 0.3, 'ink': '#2A0F06', 'sub': '#41200F'},
                      'Earth': {'c': TRIMSAMSA_COLORS['Earth']['bg'], 'o': 0.34, 'ink': '#281A0E', 'sub': '#493321'},
                      'Air': {'c': '#F8E5A2', 'o': 0.5, 'ink': '#3A2B06', 'sub': '#4C3D14'},
                      'Water': {'c': '#12386C', 'o': 0.38, 'ink': '#060B15', 'sub': '#121927'},
                      'Ether': {'c': '#7A2A86', 'o': 0.34, 'ink': '#1A0820', 'sub': '#301B36'}},
            'hora': {'Sun': {'c': '#F2D79A', 'o': 0.46, 'ink': '#3A2A08', 'sub': '#4C3C16'},
                     'Moon': {'c': '#22406E', 'o': 0.36, 'ink': '#070C16', 'sub': '#161F30'}}},
 'ash': {'id': 'ash',
         'label': 'Frêne blanchi',
         'hint': 'pale grey, sanded further and finished matte',
         'wood': 'assets/wood-ash.webp',
         'room': {'bg': '#1e1d1a',
                  'bg2': '#262520',
                  'ink': '#9e988c',
                  'dim': '#67635a',
                  'brass': '#b9964c'},
         'carve': {'lit': '#FFFCF4', 'dark': '#332C25', 'relief': 0.96},
         'wash': 0.038,
         'washAir': 0.046,
         'spine': 0.74,
         'ink': {'main': '#2F2A22',
                 'soft': '#403A31',
                 'faint': '#524B3F',
                 'lip': 'rgba(255,253,246,.55)',
                 'brass': '#B9964C',
                 'asc': '#514624',
                 'ascSub': '#4E4018',
                 'plate': '#F2EEE4',
                 'plateInk': '#241F18',
                 'plateSub': '#4A443A',
                 'marker': '#F4F0E6',
                 'focus': '#6B5A24', 'highlight': '#C8AA6B',
                 'title': '#3C362D',
                 'titleSub': '#4A443A'},
         'stain': {'Fire': {'c': TRIMSAMSA_COLORS['Fire']['bg'], 'o': 0.27, 'ink': '#2A1006', 'sub': '#412010'},
                   'Earth': {'c': TRIMSAMSA_COLORS['Earth']['bg'], 'o': 0.29, 'ink': '#281D14', 'sub': '#493829'},
                   'Air': {'c': '#CEA736', 'o': 0.31, 'ink': '#33270A', 'sub': '#433616'},
                   'Water': {'c': '#2F5887', 'o': 0.33, 'ink': '#070D1A', 'sub': '#1B2638'},
                   'Ether': {'c': '#8E3E95', 'o': 0.27, 'ink': '#1A0820', 'sub': '#33203A'}},
         'hora': {'Sun': {'c': '#CEA542', 'o': 0.29, 'ink': '#33270A', 'sub': '#433616'},
                  'Moon': {'c': '#395F8E', 'o': 0.32, 'ink': '#080E1C', 'sub': '#1C283A'}}}}
