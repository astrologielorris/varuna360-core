"""Summary bands follow existing nakshatra sectors in either angular direction.

Core (Lite too): the nakshatra wheel's property outer ring is built from these
bands. The Pro Antikythera map reuses them (its nakshatra ring module
re-exports ``NakshatraSector`` from here).
"""
from dataclasses import dataclass, replace
import math

from core.nakshatra_properties import guna_triplet, property_value, property_label, PROPERTY_OPTIONS

PROPERTY_MODES = tuple(key for key, _ in PROPERTY_OPTIONS)


@dataclass(frozen=True)
class NakshatraSector:
    identity: str
    ordinal: int
    boundary: float
    width: float
    direction: int = 1

    @property
    def draw_start(self):
        return (self.boundary - (self.width if self.direction == -1 else 0)) % 360

    @property
    def midpoint(self):
        return (self.boundary + self.direction * self.width / 2) % 360

    def contains(self, angle):
        offset = ((angle - self.boundary) * self.direction) % 360
        # Modulo may turn an exact mathematical cusp into 360-epsilon.
        if math.isclose(offset, 360, abs_tol=1e-10, rel_tol=0):
            offset = 0.0
        return offset < self.width and not math.isclose(offset, self.width, abs_tol=1e-10, rel_tol=0)


@dataclass(frozen=True)
class PropertyRun:
    boundary: float
    width: float
    direction: int
    value: str | None
    identities: tuple[str, ...]
    label: str | None = None

    @property
    def draw_start(self):
        return (self.boundary - (self.width if self.direction == -1 else 0)) % 360

    @property
    def midpoint(self):
        return (self.boundary + self.direction * self.width / 2) % 360


def property_bands(sectors, mode):
    """Return contiguous equal-value runs for each displayed property level."""
    if mode == 'none' or not sectors:
        return ()
    if mode not in PROPERTY_MODES:
        raise ValueError(f'Unsupported nakshatra property: {mode}')
    if mode != 'gunas':
        return (tuple(PropertyRun(s.boundary, s.width, s.direction, property_value(s.identity, mode),
                                  (s.identity,), property_label(s.identity, mode)) for s in sectors),)
    values = [guna_triplet(sector.identity) or (None, None, None) for sector in sectors]
    bands = []
    for level in range(3):
        runs = []
        for sector, triplet in zip(sectors, values):
            value = triplet[level]
            if runs and runs[-1].value == value:
                previous = runs[-1]
                runs[-1] = replace(previous, width=previous.width + sector.width,
                                   identities=previous.identities + (sector.identity,))
            else:
                runs.append(PropertyRun(sector.boundary, sector.width, sector.direction,
                                        value, (sector.identity,)))
        if len(runs) > 1 and runs[0].value == runs[-1].value:
            first, last = runs[0], runs[-1]
            runs = [replace(last, width=last.width + first.width,
                            identities=last.identities + first.identities)] + runs[1:-1]
        bands.append(tuple(runs))
    return tuple(bands)
