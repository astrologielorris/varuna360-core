# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Loading-overlay scope for heavy, synchronous operations (td-5qkks).

A single context manager wraps a blocking operation so the loading overlay
paints BEFORE the work runs and is always taken down afterwards, even on an
exception. It exists so the many settings-Apply fan-out handlers share one
implementation instead of each repeating the loading_manager.start/finish
dance (and each forgetting the finally, or the pre-paint).

    from managers.loading_scope import loading_scope

    with loading_scope(self, "Applying chart display..."):
        ...heavy synchronous work...

Nesting is safe: LoadingManager reference-counts, so an inner scope that also
opens the overlay does not tear it down until every scope has exited. The
overlay is parented to the main window, so it covers whichever tab is current
(including the Settings tab).

Only wrap operations that actually block long enough to be felt (measured
> ~300 ms). Wrapping a sub-300 ms operation flashes the overlay for its
minimum display time and is worse than no feedback.
"""

from contextlib import contextmanager

from PySide6.QtWidgets import QApplication


@contextmanager
def loading_scope(gui, message="Loading...", paint=True):
    """Show the loading overlay for the duration of a blocking operation.

    Args:
        gui: the ChartGUI (or any object exposing ``loading_manager``). If it
            has no loading_manager the scope is a no-op, so callers never have
            to guard for headless/partial construction.
        message: the status line shown in the overlay card.
        paint: process events once after showing the overlay so it actually
            paints before the synchronous work blocks the event loop. Leave
            True for synchronous work; pass False only when the caller drives
            its own event pumping.

    Yields the LoadingManager (or None when unavailable) so multi-step callers
    can call ``set_progress(current, total)`` / ``update(message)`` on it.
    """
    lm = getattr(gui, "loading_manager", None)
    if lm is None:
        yield None
        return
    try:
        lm.start(message)
        if paint:
            # The overlay's show_loading already calls processEvents once; this
            # is the belt-and-suspenders paint so the card is on screen before a
            # long synchronous body freezes the loop. start()/processEvents live
            # inside the try so an exception there still hits finish() (which
            # guards ref_count <= 0, so an un-started scope is a safe no-op).
            QApplication.processEvents()
        yield lm
    finally:
        lm.finish()


def run_with_loading(gui, message, fn, *args, **kwargs):
    """Call ``fn(*args, **kwargs)`` inside a loading_scope.

    A callable form of the context manager for connect() lambdas and other
    spots that cannot host a ``with`` block. Returns fn's result.
    """
    with loading_scope(gui, message):
        return fn(*args, **kwargs)
