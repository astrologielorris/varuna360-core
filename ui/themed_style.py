"""Themed-style registry mixin — SPEC-THM-001 (td-iqjb Wave F).

Problem it solves
-----------------
A panel that styles a widget ONCE at construction from a theme-aware helper
(``get_frame_style()``, ``get_3d_button_style()``, an f-string reading
``get_theme_colors()``) cannot re-style that widget on a LIVE theme switch
unless it both kept a reference AND remembered to re-apply it in
``refresh_theme()``. Frames assigned to LOCAL variables inside a ``_create_ui``
builder (``frame = QFrame(); frame.setStyleSheet(get_frame_style())``) are
unreachable once the builder returns, so they froze at construction-time
colors: correct on a light BOOT (construction read the light palette), but
near-black after a live switch to a light theme (td-iqjb.6; pre-mortem pm-004
realized at scale across the Predictive Tools sub-tabs).

Mechanism
---------
``_register_themed(widget, style_fn)`` applies ``style_fn()`` now AND records
the pair. ``refresh_theme()`` calls ``_replay_themed()`` to re-run every
recorded ``style_fn`` under the current palette. Construction and refresh
therefore share ONE code path (the ``style_fn``), so build-time and
refresh-time styling cannot drift (pm-006).

Contract for ``style_fn``
-------------------------
``style_fn`` MUST be a CALLABLE that re-evaluates the stylesheet from the
current theme on every call — the getter itself (``get_frame_style``) or a
``lambda`` that reads ``get_theme_colors()``. NEVER a pre-rendered string: a
captured string re-freezes the construction-time palette (the Wave B label
re-freeze bug this wave must not reintroduce; pm-005 = string checks prove
nothing, so the proof is pixel-sampled instead).
"""

import traceback


class ThemedStyleMixin:
    """Mix in BEFORE the Qt base class; provides the themed-style registry.

    Example::

        class EclipsePanel(ThemedStyleMixin, QWidget):
            def _create_ui(self):
                input_frame = QFrame()
                self._register_themed(input_frame, get_frame_style)
            def refresh_theme(self):
                self._replay_themed()          # frames + stateless buttons
                # ... then any widget-specific / stateful re-styling ...

    No ``__init__`` override is required: the registry list is created lazily on
    first registration, so subclasses need not call ``super().__init__`` in any
    particular order.
    """

    def _register_themed(self, widget, style_fn):
        """Apply ``style_fn()`` to ``widget`` now and record it for replay.

        Returns ``widget`` so call sites can wrap construction inline::

            frame = self._register_themed(QFrame(), get_frame_style)

        ``style_fn`` must re-evaluate from the current theme each call (see the
        module docstring contract). Applying it once here also means a single
        call site replaces the old ``widget.setStyleSheet(style_fn())`` line.
        """
        try:
            widget.setStyleSheet(style_fn())
        except Exception:
            traceback.print_exc()
        self.__dict__.setdefault("_themed_registry", []).append((widget, style_fn))
        return widget

    def _replay_themed(self):
        """Re-apply every registered ``style_fn`` under the current theme.

        Each entry is isolated (per-widget try/except) so one deleted or dead
        C++ widget cannot abort the rest — mirrors the per-surface
        ``_safe_theme`` isolation in ``core_gui_qt._on_theme_changed`` (Wave A).
        """
        for widget, style_fn in self.__dict__.get("_themed_registry", ()):
            try:
                widget.setStyleSheet(style_fn())
            except Exception:
                traceback.print_exc()
        # Effects run AFTER the stylesheet pass: a shadow's margin depends on the
        # polarity the stylesheet has just settled into (SPEC-THM-002 §6.2).
        for widget, effect_fn in self.__dict__.get("_themed_effect_registry", ()):
            try:
                effect_fn(widget)
            except Exception:
                traceback.print_exc()

    def _register_themed_effect(self, widget, effect_fn):
        """Apply ``effect_fn(widget)`` now AND record it for replay — SPEC-THM-002 §6.3.

        A QGraphicsEffect is not a stylesheet, so ``_register_themed`` cannot
        reach it: a shadow applied at construction and never replayed is a
        construction-time orphan of exactly the SPEC-THM-001 §11.6 class, one
        layer down. It survives a theme switch looking wrong rather than looking
        stale, which is harder to notice.

        ``effect_fn`` MUST re-read the live palette on every call (same contract
        as ``style_fn``) and MUST clear any existing effect before applying a new
        one, or two effects stack and the Qt-ownership dance (Rule 18) runs twice
        on one widget. ``ui.qt_theme.apply_elevation_shadow`` satisfies both.

        The §11.6 H6 lifetime rule carries over unchanged: a panel that registers
        per-chart DYNAMIC widgets must truncate BOTH registries back to its
        chrome baseline on rebuild, or the next replay calls into deleted C++
        objects.
        """
        try:
            effect_fn(widget)
        except Exception:
            traceback.print_exc()
        self.__dict__.setdefault("_themed_effect_registry", []).append(
            (widget, effect_fn))
        return widget
