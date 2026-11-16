"""Dialog shown when the user clicks 'Update Available' on the top navbar."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from backend.config.version import APP_VERSION
from backend.dto.version_dto import AppVersionDTO
from frontend import theme


class UpdateDialog(QDialog):
    def __init__(self, info: AppVersionDTO, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("GEE-Assist — Update Available")
        self.setMinimumWidth(500)
        self.setStyleSheet(
            f"QDialog {{ background: {theme.WHITE}; }}"
            f"QLabel {{ color: {theme.INK}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        # Header
        header = QLabel("A new version of GEE-Assist is available!")
        header.setStyleSheet(f"font-family: '{theme.SERIF}'; font-size: 16pt; font-weight: 600; color: {theme.INK};")
        header.setWordWrap(True)
        layout.addWidget(header)

        # Version comparison card
        version_card = QFrame()
        version_card.setStyleSheet(
            f"QFrame {{ background: {theme.FOAM}; border: 1px solid {theme.BORDER}; border-radius: 8px; padding: 12px; }}"
        )
        card_layout = QVBoxLayout(version_card)
        card_layout.setSpacing(6)

        cur_row = QLabel(f"Current installed version:  <b>v{APP_VERSION}</b>")
        new_row = QLabel(f"Latest available version:  <b style='color: {theme.OCEAN};'>v{info.latest_version}</b>")
        card_layout.addWidget(cur_row)
        card_layout.addWidget(new_row)
        layout.addWidget(version_card)

        # Release notes
        if info.release_notes:
            notes_header = QLabel("Release Notes:")
            notes_header.setStyleSheet(f"font-weight: 600; color: {theme.INK}; font-size: 11pt;")
            layout.addWidget(notes_header)

            notes_scroll = QScrollArea()
            notes_scroll.setWidgetResizable(True)
            notes_scroll.setMaximumHeight(160)
            notes_scroll.setFrameShape(QFrame.Shape.NoFrame)
            notes_scroll.setStyleSheet(
                f"QScrollArea {{ background: {theme.FIELD_BG}; border: 1px solid {theme.BORDER}; border-radius: 6px; }}"
            )

            notes_body = QLabel(info.release_notes)
            notes_body.setWordWrap(True)
            notes_body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            notes_body.setContentsMargins(12, 10, 12, 10)
            notes_body.setStyleSheet("font-size: 10pt; line-height: 1.4;")
            notes_scroll.setWidget(notes_body)
            layout.addWidget(notes_scroll)

        # Buttons
        buttons = QHBoxLayout()
        buttons.addStretch(1)

        self.later_button = QPushButton("Later", objectName="SecondaryButton")
        self.later_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.later_button.clicked.connect(self.reject)
        buttons.addWidget(self.later_button)

        self.download_button = QPushButton("Download Update", objectName="PrimaryButton")
        self.download_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.download_button.setDefault(True)
        self.download_button.clicked.connect(lambda: self._open_download(info.download_url))
        buttons.addWidget(self.download_button)

        layout.addLayout(buttons)

    def _open_download(self, url: str | None) -> None:
        if url:
            QDesktopServices.openUrl(QUrl(url))
        self.accept()
