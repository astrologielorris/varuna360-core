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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from core.pro_marketing import (
    PRO_UPGRADE_URL,
    TIER_FREE_NAME, TIER_FREE_PRICE, TIER_FREE_FEATURES,
    TIER_MOBILE_NAME, TIER_MOBILE_PRICE, TIER_MOBILE_FEATURES,
    TIER_EXPLORATEUR_NAME, TIER_EXPLORATEUR_PRICE, TIER_EXPLORATEUR_FEATURES,
    TIER_PRO_NAME, TIER_PRO_PRICE, TIER_PRO_FEATURES, TIER_PRO_COMING_SOON,
)

from ui.qt_theme import scaled_area_font, GOLD, TEXT_SECONDARY


class TierDialog(QDialog):
    """Non-modal four-column plan comparison dialog."""

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
        header.setFont(scaled_area_font('panel_titles', bold=True))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        subtitle = QLabel(
            "This desktop app is included in the Explorateur plan. Copy your "
            "license key from your 360heartsinthesky.com account and paste it "
            "into the app (License menu) to activate it."
        )
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        # ── Four columns, website display order. Explorateur (the plan that
        #    unlocks this app) is highlighted; Pro is greyed coming-soon. ──
        columns = QHBoxLayout()
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
        layout.addLayout(columns)

        # ── Footer buttons ──
        footer = QHBoxLayout()
        footer.setSpacing(8)

        subscribe_btn = QPushButton("Subscribe at 360heartsinthesky.com")
        subscribe_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        subscribe_btn.clicked.connect(self._on_subscribe_clicked)
        footer.addWidget(subscribe_btn)

        footer.addStretch(1)

        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)

        layout.addLayout(footer)

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
        name_label.setFont(scaled_area_font('tables', bold=True))
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if muted_css:
            name_label.setStyleSheet(muted_css)
        col_layout.addWidget(name_label)

        if tag:
            tag_label = QLabel(tag)
            tag_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if highlight:
                tag_label.setStyleSheet(f"color: {GOLD}; font-weight: bold; border: none;")
            else:
                tag_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-style: italic; border: none;")
            col_layout.addWidget(tag_label)

        price_label = QLabel(price)
        price_label.setFont(scaled_area_font('tables'))
        price_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if muted_css:
            price_label.setStyleSheet(muted_css)
        col_layout.addWidget(price_label)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        col_layout.addWidget(separator)

        for feature in features:
            bullet = QLabel(f"•  {feature}")
            bullet.setWordWrap(True)
            if muted_css:
                bullet.setStyleSheet(muted_css)
            col_layout.addWidget(bullet)

        col_layout.addStretch(1)
        return frame

    def _on_subscribe_clicked(self) -> None:
        """Open the subscription page in the default browser."""
        webbrowser.open(PRO_UPGRADE_URL)
