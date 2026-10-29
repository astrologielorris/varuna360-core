# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The exchange RANK (SPEC-EXCH-002 §3.2, td-m79zy): one pure rule, shared by
the EXCH panel, the chain overlay and ``show_dispositors``.

Houses a, b of the exchange (whole sign), first rule that matches:
  {6, 8}                      -> 1 Most difficult
  8 in the houses             -> 2 Very difficult
  6 or 12 in the houses       -> 3 Difficult
  KHALA                       -> 4 Mixed
  MAHA with 1, 5, 9 or 10     -> 6 Very good
  other MAHA (2, 4, 7, 11)    -> 5 Good
The words and short lines are Lorris's approved draft wording (English source;
the GUI routes them through t()). Qt-free, no GUI state.
"""
from __future__ import annotations

from typing import NamedTuple

_RAJA_HOUSES = frozenset((1, 5, 9, 10))
# the EXCH panel's card order (ParivartanaWidget._CLASS_ORDER); letters A, B, C
# name the exchanges of a 2- or 3-exchange chart in that order
CLASS_ORDER = ("MAHA", "KHALA", "DAINYA_6", "DAINYA_8", "DAINYA_12", "DAINYA_DOUBLE")
LETTERS = ("A", "B", "C")

RANK_KEYS = {1: "most_difficult", 2: "very_difficult", 3: "difficult",
             4: "mixed", 5: "good", 6: "very_good"}
RANK_WORDS = {1: "Most difficult", 2: "Very difficult", 3: "Difficult",
              4: "Mixed", 5: "Good", 6: "Very good"}
RANK_LINES = {6: "Maha with the 1st, 5th, 9th or 10th",
              5: "Maha between 2, 4, 7 and 11 only",
              4: "Khala: the 3rd with a non-dusthana house",
              3: "the 6th or the 12th with any other house",
              2: "the 8th with any other house",
              1: "the 6th and the 8th exchange"}


class Marks(NamedTuple):
    """The house marks drawn on a chain: the 6th = sick metal, the 12th =
    see-through, the 8th = chaos, rank 1 = broken."""
    sick: bool
    see_through: bool
    chaos: bool
    broken: bool

    def names(self):
        return [n for n, on in zip(("sick", "see_through", "chaos", "broken"), self) if on]


def exchange_rank(house_a: int, house_b: int, cls: str | None = None) -> int:
    """Rank 1 (most difficult) .. 6 (very good) of an exchange between two
    whole-sign houses. ``cls`` is the engine class (MAHA / KHALA / DAINYA_*);
    when None it is derived from the houses the engine's way."""
    houses = {int(house_a), int(house_b)}
    if houses == {6, 8}:
        return 1
    if 8 in houses:
        return 2
    if 6 in houses or 12 in houses:
        return 3
    if cls is None:
        cls = "KHALA" if 3 in houses else "MAHA"
    if cls == "KHALA":
        return 4
    return 6 if houses & _RAJA_HOUSES else 5


def house_marks(house_a: int, house_b: int, rank: int) -> Marks:
    houses = {int(house_a), int(house_b)}
    return Marks(6 in houses, 12 in houses, 8 in houses, rank == 1)


def rank_record(rec):
    """``{rank, rank_key, rank_label, marks}`` for one frozen 7-tuple record."""
    _pa, _sa, ha, _pb, _sb, hb, cls = rec
    rank = exchange_rank(ha, hb, cls)
    return {"rank": rank, "rank_key": RANK_KEYS[rank], "rank_label": RANK_WORDS[rank],
            "marks": house_marks(ha, hb, rank).names()}
