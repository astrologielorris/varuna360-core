"""South Indian chain surfaces and the classic (image) view's chain pass
(SPEC-EXCH-002 3.4.2, td-s7qzl).

A South Indian surface is ``(name, cell, rect_of, centre box)``: a sign's card is
its grid cell inset by ``gutter``, the centre box the 2 x 2 centre inset the same.
The vector view and the classic view differ only in where the numbers come from.
"""
from apps.widgets.exchange_chain_items import si_pass

POSITIONS = {}          # sign index -> (row, col), filled on first use (chart_view import)
VECTOR_GUTTER_RATIO = 12 / 512      # the vector card inset (south_indian_geometry.GUTTER)


def _cells():
    if not POSITIONS:
        from apps.widgets.chart_view import SouthIndianView
        POSITIONS.update({sign: cell for cell, sign in SouthIndianView.ZODIAC_POSITIONS.items()})
    return POSITIONS


def si_surface(name, cell, gutter):
    """(name, cell, rect_of, centre box) of a South Indian scene of 4 x 4 ``cell``."""
    cells = _cells()

    def rect_of(sign):
        row, col = cells[sign]
        return col * cell + gutter, row * cell + gutter, cell - 2 * gutter, cell - 2 * gutter
    return name, cell, rect_of, (cell + gutter, cell + gutter, 3 * cell - gutter, 3 * cell - gutter)


def vector_surface():
    from apps.widgets.south_indian_geometry import CELL_SIZE, GUTTER
    return si_surface("vector", CELL_SIZE, GUTTER)


def classic_surface(view):
    """Read from the view (INV-2): its cell size, the vector card inset to scale."""
    cell = float(view.cell_size)
    return si_surface("classic", cell, cell * VECTOR_GUTTER_RATIO)


def classic_si_pass(view, get=None):
    """THE chain pass of a classic South Indian view. Returns the items added."""
    return si_pass(view, get, classic_surface(view))
