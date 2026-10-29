"""Planet grid for one North Indian cell, sized for the degree labels (stateless).

An enlarged Planet Degrees label (above the per-view base) is capped at the size
whose widest label still fits its planet slot, never below the base, so labels
in a small triangle do not run into each other; the reserve under each planet
grows with it. At the base size grid, reserve and label are the former ones.
"""

LABEL_WIDTH_PER_PT = 4.0   # width of a "24°43'" label, in units of its point size
NAME_WIDTH_PER_PT = 5.6    # width of a planet name ("Mercury", F11 names mode)
BASE_LABEL_RESERVE = 22    # px under each planet for its degree label, at the base size


def degree_grid(count, rect_w, deg_size, base_size, names=False):
    """(cols, rows, label_reserve, label_size) for ``count`` planets in a
    ``rect_w`` wide zone, the label asked at ``deg_size`` (base ``base_size``);
    ``names``: the labels are planet names (F11), wider than degrees."""
    if count <= 3:
        cols, rows = max(count, 1), 1
    elif count == 4:
        cols, rows = 2, 2
    elif count <= 6:
        cols, rows = 3, 2
    elif count <= 9:
        cols, rows = 3, 3
    else:
        cols, rows = 4, (count + 3) // 4
    if deg_size <= base_size:
        return cols, rows, BASE_LABEL_RESERVE, deg_size
    fit = int(rect_w / cols * 0.9 / (NAME_WIDTH_PER_PT if names else LABEL_WIDTH_PER_PT))
    size = max(base_size, min(deg_size, fit))
    return cols, rows, BASE_LABEL_RESERVE * size / base_size, size
