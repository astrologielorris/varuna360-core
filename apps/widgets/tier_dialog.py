# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Tier Dialog: side-by-side comparison of the Varuna360 subscription plans.

Opened from the License > View Plans menu. Non-modal so the user can
keep exploring the app while they read. Shows what each plan unlocks;
the Explorateur plan is the one whose license key activates this desktop app.
Pro is a coming-soon plan and is shown greyed, never offered for purchase.

All copy comes from core/pro_marketing.py constants — the SINGLE point
of tier-related text in Core. If the website renames a plan or
changes its features, update pro_marketing.py and this dialog picks
up the change automatically.
"""

from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from core.pro_marketing import (
    PRO_UPGRADE_URL,
    TIER_FREE_NAME, TIER_FREE_PRICE, TIER_FREE_FEATURES,
    TIER_MOBILE_NAME, TIER_MOBILE_PRICE, TIER_MOBILE_FEATURES,
    TIER_EXPLORATEUR_NAME, TIER_EXPLORATEUR_PRICE, TIER_EXPLORATEUR_FEATURES,
    TIER_PRO_NAME, TIER_PRO_PRICE, TIER_PRO_FEATURES, TIER_PRO_COMING_SOON,
)

from ui.qt_theme import scaled_area_px, GOLD, TEXT_SECONDARY
from ui.popup_fonts import tier_px, popup_title_px, live_refresh, live_style


class TierDialog(QDialog):
    """Non-modal four-column plan comparison dialog. Its text styles are live
    (ui.popup_fonts.live_style): an open Plans window follows a Fonts Apply."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Varuna360 Plans")
        self.setModal(False)
        self.setMinimumWidth(980)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 20, 24, 20)

        # ── Header ──
        header = QLabel("Plans")
        # O-6: font-size in QSS, not setFont (qt-material overrides setFont).
        live_style(self, header, lambda: f"font-size: {popup_title_px(14)}px; font-weight: bold;")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        subtitle = QLabel(
            "This desktop app is included in the Explorateur plan. Copy your "
            "license key from your 360heartsinthesky.com account and paste it "
            "into the app (License menu) to activate it."
        )
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # O-6: font-size in QSS (this is descriptive body text -> info_text).
        live_style(self, subtitle, lambda: f"font-size: {scaled_area_px('info_text')}px;")
        layout.addWidget(subtitle)

        # ── Four columns, website display order. Explorateur (the plan that
        #    unlocks this app) is highlighted; Pro is greyed coming-soon. ──
        column_host = QWidget()
        columns = QHBoxLayout(column_host)
        columns.setSpacing(12)
        columns.addWidget(self._make_tier_column(
            TIER_FREE_NAME, TIER_FREE_PRICE, TIER_FREE_FEATURES,
        ))
        columns.addWidget(self._make_tier_column(
            TIER_MOBILE_NAME, TIER_MOBILE_PRICE, TIER_MOBILE_FEATURES,
        ))
        columns.addWidget(self._make_tier_column(
            TIER_EXPLORATEUR_NAME, TIER_EXPLORATEUR_PRICE, TIER_EXPLORATEUR_FEATURES,
            highlight=True, tag="Unlocks this app",
        ))
        columns.addWidget(self._make_tier_column(
            TIER_PRO_NAME, TIER_PRO_PRICE, TIER_PRO_FEATURES,
            muted=bool(TIER_PRO_COMING_SOON),
            tag="Coming soon" if TIER_PRO_COMING_SOON else "",
        ))
        self._columns = column_host
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(column_host)
        layout.addWidget(scroll, 1)

        # ── Footer buttons ──
        footer = QHBoxLayout()
        footer.setSpacing(8)

        # O-6: font-size in QSS on the footer buttons (bottom row -> action_buttons).
        def _btn_size():
            return f"font-size: {tier_px('action_buttons', 10)}px;"

        subscribe_btn = QPushButton("Subscribe at 360heartsinthesky.com")
        subscribe_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        live_style(self, subscribe_btn, _btn_size)
        subscribe_btn.clicked.connect(self._on_subscribe_clicked)
        footer.addWidget(subscribe_btn)

        footer.addStretch(1)

        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        live_style(self, close_btn, _btn_size)
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)

        layout.addLayout(footer)
        # Registered last and deferred one event-loop pass: the labels' new
        # height-for-width exists only once the style change has been processed.
        live_refresh(self, lambda: QTimer.singleShot(0, self._fit_height))

    def _fit_height(self) -> None:
        """Fit current content, capped to the available screen. The columns
        scroll inside that cap so the footer always remains reachable."""
        lay = self.layout()
        lay.activate()
        content = self._columns.layout()
        content.activate()
        need = content.totalSizeHint().height() + 130
        if need > 0:
            screen = self.screen() or QApplication.primaryScreen()
            cap = max(400, screen.availableGeometry().height() - 48)
            target = min(need, cap)
            self.setMinimumHeight(min(target, 400))
            self.resize(self.width(), target)

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_height()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self._fit_height()

    def _make_tier_column(
        self, name: str, price: str, features: tuple[str, ...],
        highlight: bool = False, tag: str = "", muted: bool = False,
    ) -> QFrame:
        """Build a single plan column.

        `highlight` draws a gold border and a gold `tag` under the name (the
        plan that unlocks this app). `muted` greys the whole column and shows
        `tag` in muted text (a coming-soon plan that is not yet purchasable).
        """
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        if highlight:
            # ID selector so the gold border applies to THIS frame only and does
            # not cascade onto child QFrames (the separator) or labels.
            frame.setObjectName("planColHighlight")
            frame.setStyleSheet(
                "QFrame#planColHighlight { border: 2px solid %s; border-radius: 6px; }" % GOLD
            )

        muted_css = f"color: {TEXT_SECONDARY}; border: none;" if muted else ""

        col_layout = QVBoxLayout(frame)
        col_layout.setSpacing(6)
        col_layout.setContentsMargins(14, 14, 14, 14)

        name_label = QLabel(name)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # O-6: always set font-size in QSS (appended to the muted colour if any).
        live_style(self, name_label, lambda: (muted_css + " " if muted_css else "")
                   + f"font-size: {popup_title_px(11)}px; font-weight: bold;")
        col_layout.addWidget(name_label)

        if tag:
            tag_label = QLabel(tag)
            tag_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # O-6: font-size in QSS on both branches (small caption -> buttons).
            tag_css = (f"color: {GOLD}; font-weight: bold; border: none;" if highlight
                       else f"color: {TEXT_SECONDARY}; font-style: italic; border: none;")
            live_style(self, tag_label,
                       lambda: f"{tag_css} font-size: {tier_px('status', 10)}px;")
            col_layout.addWidget(tag_label)

        price_label = QLabel(price)
        price_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        live_style(self, price_label, lambda: (muted_css + " " if muted_css else "")
                   + f"font-size: {scaled_area_px('info_text')}px;")
        col_layout.addWidget(price_label)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        col_layout.addWidget(separator)

        for feature in features:
            bullet = QLabel(f"•  {feature}")
            bullet.setWordWrap(True)
            # O-6: font-size in QSS always (feature body text -> info_text),
            # appended to the muted colour if this column is greyed.
            live_style(self, bullet, lambda: (muted_css + " " if muted_css else "")
                       + f"font-size: {scaled_area_px('info_text')}px;")
            col_layout.addWidget(bullet)

        col_layout.addStretch(1)
        return frame

    def _on_subscribe_clicked(self) -> None:
        """Open the subscription page in the default browser."""
        webbrowser.open(PRO_UPGRADE_URL)
