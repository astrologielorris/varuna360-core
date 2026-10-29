# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""When the panel may compute without asking (SPEC-FIND-003 §3.6, SPEC-FIND-004
§5.2, design.md §4.6). Qt-free, so the rule is tested without a window.

- A plan at or under ``compute.CONSENT_THRESHOLD_S`` counts as consented.
- Above it, the panel asks, but only for work the user asked for: an
  extractor that owns one of the query's filters. "Don't ask again" turns
  that question into a yes.
- A gap nobody asked for (Positions for the result columns after the app's
  mode changed, say) is only offered: the coverage strip's Compute button.
- A declined or cancelled plan is not offered again until the query changes
  (``PlanKey``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from core.chart_search.compute import ComputePlan
from core.chart_search.search import Scope
from core.chart_search.system import SearchSystem

#: The settings registry key behind "Don't ask again" (house rule 2).
DONT_ASK_KEY = "ui.find_chart_compute_dont_ask"


class Decision(StrEnum):
    NOTHING = "nothing"  # nothing missing
    RUN = "run"  # consented: under the threshold, or "Don't ask again"
    ASK = "ask"  # the confirmation dialog
    OFFER = "offer"  # leave it to the coverage strip's Compute button


@dataclass(frozen=True)
class PlanKey:
    """What a plan was made for; a declined key is not asked about again."""

    system: SearchSystem
    extractors: frozenset[str]
    scope: Scope


def key_of(plan: ComputePlan, scope: Scope) -> PlanKey:
    return PlanKey(
        plan.system, frozenset(item.extractor.id for item in plan.items), scope
    )


def decide(
    plan: ComputePlan,
    *,
    requested: frozenset[str],
    dont_ask: bool,
    declined: bool,
) -> Decision:
    """``requested``: ids of the extractors that own the query's filters."""
    if plan.empty:
        return Decision.NOTHING
    if declined:
        return Decision.OFFER
    if not plan.needs_consent():
        return Decision.RUN
    if not any(item.extractor.id in requested for item in plan.items):
        return Decision.OFFER
    return Decision.RUN if dont_ask else Decision.ASK
