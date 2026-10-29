"""
The chart index behind Find Chart.

``ChartIndexCache`` is a handle on the Find Chart store
(``core.chart_search.store``, design.md §4.11): Pro constructs it with no
arguments (pro-boundary.md §3.8 item 1) and uses none of the old JSON query
surface, which is retired, not migrated. The old JSON index file is neither
read nor deleted.
"""


class ChartIndexCache:
    """The Find Chart store at ``store_path()``. Constructing it touches no
    file; ``reader()`` raises ``NoIndexError`` until an index is built,
    ``writer()`` creates the store."""

    def __init__(self) -> None:
        from core.chart_search.store import store_path

        self.path = store_path()

    def reader(self):
        """A read-only ``StoreReader`` (a context manager)."""
        from core.chart_search.store import StoreReader

        return StoreReader.open(self.path)

    def writer(self):
        """A ``StoreWriter`` (a context manager); follow SPEC-FIND-003 on
        what may write without the user's consent."""
        from core.chart_search.store import StoreWriter

        return StoreWriter.open(self.path)
