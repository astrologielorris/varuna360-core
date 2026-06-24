"""Typed events for Layer B state mutations (COMM-06 §4)."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SetActiveChart:
    """New chart loaded or selected from memory."""
    chart: object = None
    source_params: Optional[dict] = None


@dataclass
class SetVarga:
    """User switched divisional chart."""
    varga_number: int = 1


@dataclass
class SetZodiacMode:
    """User switched zodiac display mode."""
    mode: str = "aditya"


@dataclass
class SetTimeAdjustMode:
    """User toggled rectification mode."""
    enabled: bool = False


@dataclass
class SetChartViewStyle:
    """User switched chart view (south_indian/north_indian/wheel)."""
    style: str = "south_indian"


@dataclass
class SetHouseSystem:
    """User switched the house system (SPEC-HSY-001)."""
    house_system: str = "campanus"  # human key, NOT the Swiss Ephemeris code
