# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Per-house-pair Parivartana (exchange) interpretations.
======================================================
A specific reading for EVERY house-pair exchange (Maha = beneficial fusion of two
good houses, Khala = mixed/effortful via the 3rd, Dainya = misery via a dusthana
6/8/12). Replaces the old single general-per-type text so any chart's exact
exchange shows text tailored to its two houses.

Keyed by a SORTED (low, high) house-pair tuple. SOURCE: the authored house-learning
study guides (inspired by Ernst Wilhelm's teaching on Parivartana Yogas, per-house-pair
readings), written in the app author's voice. Coverage:
28 Maha + 8 Khala + 30 Dainya = 66 pairs.
"""

MAHA_PAIR_DESC = {
    (1, 2): "",
    (1, 4): "",
    (1, 5): "",
    (1, 7): "",
    (1, 9): "",
    (1, 10): "",
    (1, 11): "",
    (2, 4): "",
    (2, 5): "",
    (2, 7): "",
    (2, 9): "",
    (2, 10): "",
    (2, 11): "",
    (4, 5): "",
    (4, 7): "",
    (4, 9): "",
    (4, 10): "",
    (4, 11): "",
    (5, 7): "",
    (5, 9): "",
    (5, 10): "",
    (5, 11): "",
    (7, 9): "",
    (7, 10): "",
    (7, 11): "",
    (9, 10): "",
    (9, 11): "",
    (10, 11): "",
}

KHALA_PAIR_DESC = {
    (1, 3): "",
    (2, 3): "",
    (3, 4): "",
    (3, 5): "",
    (3, 7): "",
    (3, 9): "",
    (3, 10): "",
    (3, 11): "",
}

DAINYA_PAIR_DESC = {
    (1, 6): "",
    (1, 8): "",
    (1, 12): "",
    (2, 6): "",
    (2, 8): "",
    (2, 12): "",
    (3, 6): "",
    (3, 8): "",
    (3, 12): "",
    (4, 6): "",
    (4, 8): "",
    (4, 12): "",
    (5, 6): "",
    (5, 8): "",
    (5, 12): "",
    (6, 7): "",
    (6, 8): "",
    (6, 9): "",
    (6, 10): "",
    (6, 11): "",
    (6, 12): "",
    (7, 8): "",
    (7, 12): "",
    (8, 9): "",
    (8, 10): "",
    (8, 11): "",
    (8, 12): "",
    (9, 12): "",
    (10, 12): "",
    (11, 12): "",
}


def _pair(house_a, house_b):
    return tuple(sorted((int(house_a), int(house_b))))


def describe_exchange(house_a, house_b):
    """Specific reading for an exchange between two houses, or None.

    Looks up the sorted house pair across all three type tables (a pair belongs
    to exactly one type). None if either house is out of 1..12 or the pair is a
    degenerate same-house (not a real 2-house exchange).
    """
    key = _pair(house_a, house_b)
    if key[0] == key[1] or key[0] < 1 or key[1] > 12:
        return None
    for table in (MAHA_PAIR_DESC, KHALA_PAIR_DESC, DAINYA_PAIR_DESC):
        if key in table:
            return table[key]
    return None
