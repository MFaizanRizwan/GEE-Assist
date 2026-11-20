"""Dialog shown when the user clicks 'Update Available' on the top navbar.

"Update Now" downloads the new version's installer (with a progress bar), starts it and closes
the app so the installer can replace it.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from backend.business.facade.i_business_facade import IBusinessFacade
from backend.config.version import APP_VERSION
from backend.dto.version_dto import AppVersionDTO
from backend.exceptions import UpdateCancelledError
from frontend import theme
from frontend.workers.task_worker import run_task

_MB = 1024 * 1024


class _Progress(QObject):
    """Carries download progress from the worker thread to the dialog (queued onto the UI thread).

    Not parented to the dialog: the worker keeps it alive until the download ends, even if the
    dialog has been closed by then."""

    changed = pyqtSignal(int, int)  # bytes received, total bytes (0 = unknown)


class UpdateDialog(QDialog):
    def __init__(self, facade: IBusinessFacade, info: AppVersionDTO, parent: QWidget | None = None):
        super().__init__(parent)
        self._facade = facade
        self._info = info
        self._cancel = threading.Event()
        self._downloading = False

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

        # Download progress (shown once the download starts)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size: 10pt;")
        self.status_label.hide()
        layout.addWidget(self.status_label)

        # Buttons
        buttons = QHBoxLayout()
        buttons.addStretch(1)

        self.later_button = QPushButton("Later", objectName="SecondaryButton")
        self.later_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.later_button.clicked.connect(self.reject)
        buttons.addWidget(self.later_button)

        self.update_button = QPushButton("Update Now", objectName="PrimaryButton")
        self.update_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_button.setDefault(True)
        self.update_button.clicked.connect(self.start_update)
        buttons.addWidget(self.update_button)

        layout.addLayout(buttons)

    # ------------------------------------------------------------- download
    def start_update(self) -> None:
        if self._downloading:
            return
        self._downloading = True
        self._cancel.clear()
        self.update_button.setEnabled(False)
        self.update_button.setText("Downloading…")
        self.later_button.setText("Cancel")
        self.progress_bar.setRange(0, 0)  # busy until the size is known
        self.progress_bar.show()
        self._show_status("Downloading the update…")

        progress = _Progress()
        progress.changed.connect(self._on_progress)
        last = [-1]

        def report(received: int, total: int | None) -> None:
            # Called on the worker thread; only send whole-percent (or whole-MB) steps to the UI.
            step = received * 100 // total if total else received // _MB
            if step != last[0]:
                last[0] = step
                progress.changed.emit(received, total or 0)

        run_task(
            self,
            self._facade.download_update,
            self._info.download_url or "",
            report,
            self._cancel.is_set,
            on_success=self._on_downloaded,
            on_error=self._on_failed,
        )

    def _on_progress(self, received: int, total: int) -> None:
        if total:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(received * 100 // total)
            self._show_status(f"Downloading the update… {received / _MB:.1f} of {total / _MB:.1f} MB")
        else:
            self._show_status(f"Downloading the update… {received / _MB:.1f} MB")

    def _on_downloaded(self, installer: Path) -> None:
        self._downloading = False
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self._show_status("Starting the installer… GEE-Assist will close so it can be updated.")
        try:
            self._facade.install_update(installer)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self._on_failed(exc)
            return
        self.accept()
        QApplication.quit()  # the active download is paused first (see app.py)

    def _on_failed(self, error: BaseException) -> None:
        self._downloading = False
        self.progress_bar.hide()
        self.later_button.setText("Later")
        self.update_button.setEnabled(True)
        self.update_button.setText("Try Again")
        if isinstance(error, UpdateCancelledError):
            self.status_label.hide()
            self.update_button.setText("Update Now")
            return
        self._show_status(str(error) or "The update failed.", error=True)

    def _show_status(self, text: str, error: bool = False) -> None:
        colour = theme.ERROR if error else theme.INK
        self.status_label.setStyleSheet(f"font-size: 10pt; color: {colour};")
        self.status_label.setText(text)
        self.status_label.show()

    # ------------------------------------------------------------- closing
    def reject(self) -> None:
        """'Later', 'Cancel' or Esc: stop a running download, then close."""
        self._cancel.set()
        super().reject()
