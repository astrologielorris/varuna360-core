"""KEYBOARD SHORTCUTS & NAV cluster, extracted from ChartGUI (Stage 1b, move-only).

Move-only mixin per the split-investigation plan Option 4 (see
proprietary_docs/docs/god_object_decomposition/). Method BODIES are moved
byte-identically (AST-identical); ChartGUI inherits this mixin so every
self.* resolves unchanged via the MRO and no self.gui.* write is created.
This cluster's methods already import everything they need method-locally
(QShortcut/QKeySequence inside _setup_keyboard_shortcuts), so like the Kala
mixin this module needs ZERO top-level imports and introduces no import cycle.
"""


class KeyboardNavMixin:
    """KEYBOARD SHORTCUTS & NAV behaviour for ChartGUI (see module docstring)."""

    def _setup_keyboard_shortcuts(self):
        """Register all keyboard shortcuts using QShortcut.

        Uses QShortcut instead of keyPressEvent so shortcuts work regardless
        of which child widget has focus (QGraphicsView, buttons, etc.).

        Arrow keys: chart/tab navigation
        Alt+key: toolbar button shortcuts
        """
        from PySide6.QtGui import QShortcut, QKeySequence

        # ── Alt+Arrow: chart/tab navigation ──
        QShortcut(QKeySequence("Alt+Left"), self, self._prev_chart)
        QShortcut(QKeySequence("Alt+Right"), self, self._next_chart)
        QShortcut(QKeySequence("Alt+Up"), self, self._prev_tab)
        QShortcut(QKeySequence("Alt+Down"), self, self._next_tab)

        # ── Alt+PageUp/PageDown: memory panel page navigation ──
        QShortcut(QKeySequence("Alt+PgUp"), self, self._prev_memory_page)
        QShortcut(QKeySequence("Alt+PgDown"), self, self._next_memory_page)

        # ── Alt+key: toolbar buttons ──
        # SPEC-BAR-001 D-23(e): Open in Kala moves Alt+K → Alt+O ("O for
        # Open"), freeing Alt+K for CARDS. This rebind is ATOMIC — both lines
        # land together; splitting them would leave Alt+K momentarily bound to
        # two handlers and Qt would fire NEITHER (ambiguous shortcut).
        QShortcut(QKeySequence("Alt+O"), self, self._open_in_kala)
        QShortcut(QKeySequence("Alt+K"), self, self._toggle_cards_view)
        QShortcut(QKeySequence("Alt+W"), self, self._toggle_wheel_view)
        QShortcut(QKeySequence("Alt+N"), self, self._load_now_chart)
        QShortcut(QKeySequence("Alt+A"), self, self.show_add_chart_dialog)
        QShortcut(QKeySequence("Alt+T"), self, self._toggle_time_adjust)
        # C7: Ctrl+Shift+H runs the SAME 3-state Human Design cycle as the
        # relocated left-group button — bodygraph page -> -88 Design chart ->
        # wheel. (Was WI-6's page-only toggle; the page and the -88 mode are now
        # one control per Lorris.)
        QShortcut(QKeySequence("Ctrl+Shift+H"), self, self._cycle_human_design)

    def _prev_chart(self):
        """Navigate to previous chart in memory panel."""
        if hasattr(self, 'memory_panel') and self.memory_panel.current_index > 0:
            self.memory_panel.select_chart(self.memory_panel.current_index - 1)

    def _next_chart(self):
        """Navigate to next chart in memory panel."""
        if hasattr(self, 'memory_panel') and self.memory_panel.current_index < len(self.memory_panel.charts) - 1:
            self.memory_panel.select_chart(self.memory_panel.current_index + 1)

    def _prev_tab(self):
        """Navigate to previous tab."""
        idx = self.tab_widget.currentIndex()
        if idx > 0:
            self.tab_widget.setCurrentIndex(idx - 1)

    def _next_tab(self):
        """Navigate to next tab."""
        idx = self.tab_widget.currentIndex()
        if idx < self.tab_widget.count() - 1:
            self.tab_widget.setCurrentIndex(idx + 1)

    def _prev_memory_page(self):
        """Navigate to previous page in memory panel."""
        if hasattr(self, 'memory_panel'):
            self.memory_panel.prev_page()

    def _next_memory_page(self):
        """Navigate to next page in memory panel."""
        if hasattr(self, 'memory_panel'):
            self.memory_panel.next_page()
