"""The update dialog: shows the new version and updates the app in place.

"Update now" downloads the new GEE-Assist.exe (with progress; it can be cancelled), checks it
(a Windows program, the published SHA-256 if any, and that it starts and is the version
announced), puts it in place of the running .exe wherever that was installed, and restarts.
If the folder needs administrator rights, Windows asks once, and a helper finishes after the
app closes. When the server says the update is required (``force_update``), the dialog offers
no "Later": update now, or quit.

Run from source (not the packaged .exe), there is no .exe to replace: the download page opens.
"""

from __future__ import annotations

import threading

from PyQt6.QtCore import QProcess, Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
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

from backend.config.version import APP_VERSION
from backend.dto.version_dto import AppVersionDTO
from backend.exceptions import GeeAssistError, UpdateError
from frontend import theme
from frontend.workers.task_worker import run_task


class _Progress:
    def __init__(self) -> None:
        self.done = 0
        self.total = 0
        self.cancel = threading.Event()

    def __call__(self, done: int, total: int) -> None:
        self.done, self.total = done, total


class UpdateDialog(QDialog):
    def __init__(self, info: AppVersionDTO, facade=None, parent: QWidget | None = None):
        super().__init__(parent)
        self.info = info
        self._facade = facade
        self.forced = bool(info.force_update)
        self.state = "idle"          # idle, downloading, installing, done, failed
        self._progress = _Progress()
        self.setWindowTitle("GEE-Assist — Update " + ("required" if self.forced else "available"))
        self.setMinimumWidth(520)
        self.setStyleSheet(f"QDialog {{ background: {theme.WHITE}; }} QLabel {{ color: {theme.INK}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        header = QLabel("This version of GEE-Assist must be updated to keep working." if self.forced
                        else "A new version of GEE-Assist is available!")
        header.setStyleSheet(f"font-family: '{theme.SERIF}'; font-size: 16.2pt; font-weight: 600;")
        header.setWordWrap(True)
        layout.addWidget(header)

        card = QFrame()
        card.setStyleSheet(f"QFrame {{ background: {theme.FOAM}; border: 1px solid {theme.BORDER}; "
                           "border-radius: 8px; padding: 12px; }}")
        card_layout = QVBoxLayout(card)
        card_layout.addWidget(QLabel(f"Installed version:  <b>v{APP_VERSION}</b>"))
        card_layout.addWidget(QLabel(f"New version:  <b style='color: {theme.OCEAN};'>v{info.latest_version}</b>"))
        layout.addWidget(card)

        if info.release_notes:
            notes = QLabel(info.release_notes)
            notes.setWordWrap(True)
            notes.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            notes.setContentsMargins(12, 10, 12, 10)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setMaximumHeight(160)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(notes)
            layout.addWidget(QLabel("<b>Release notes</b>"))
            layout.addWidget(scroll)

        self.status = QLabel(self._idle_text())
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color: {theme.MUTED};")
        layout.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.hide()
        layout.addWidget(self.bar)

        buttons = QHBoxLayout()
        self.page_button = QPushButton("Open download page", objectName="SecondaryButton")
        self.page_button.setVisible(bool(info.download_url))
        self.page_button.clicked.connect(self.open_page)
        buttons.addWidget(self.page_button)
        buttons.addStretch(1)
        self.later_button = QPushButton("Quit GEE-Assist" if self.forced else "Later", objectName="SecondaryButton")
        self.later_button.clicked.connect(self._later)
        buttons.addWidget(self.later_button)
        self.update_button = QPushButton("Update now", objectName="PrimaryButton")
        self.update_button.setDefault(True)
        self.update_button.setEnabled(bool(info.download_url))
        self.update_button.clicked.connect(self.start)
        buttons.addWidget(self.update_button)
        for button in (self.page_button, self.later_button, self.update_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tick)

    def _idle_text(self) -> str:
        if not self.info.download_url:
            return "No download is published for this version yet."
        if self._facade is None or not self._facade.can_self_update():
            return "GEE-Assist is running from its source code here: “Update now” opens the download page."
        return ("“Update now” downloads the new version, checks it, replaces this copy of GEE-Assist where it is "
                "installed and restarts it. Your settings and projects are kept.")

    # ------------------------------------------------------------- updating
    def start(self) -> None:
        if self._facade is None or not self._facade.can_self_update():
            self.open_page()
            return
        self.state = "downloading"
        self.update_button.setEnabled(False)
        self.later_button.setText("Cancel")
        self.bar.show()
        self.bar.setValue(0)
        self.status.setText("Downloading the new version…")
        self._progress = _Progress()
        self._timer.start()
        run_task(self, self._facade.download_update, self.info, self._progress, self._progress.cancel.is_set,
                 on_success=self._downloaded, on_error=self._failed)

    def _tick(self) -> None:
        done, total = self._progress.done, self._progress.total
        if self.state != "downloading":
            return
        if total:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(done / total * 1000))
            self.status.setText(f"Downloading the new version… {done / 1e6:,.0f} of {total / 1e6:,.0f} MB")
        else:
            self.bar.setRange(0, 0)   # size unknown: a busy bar
            self.status.setText(f"Downloading the new version… {done / 1e6:,.0f} MB")
        if total and done >= total:
            self.status.setText("Checking the new version (it is started once to confirm it works)…")

    def _downloaded(self, new_file) -> None:
        self.state = "installing"
        self._timer.stop()
        self.bar.setRange(0, 0)
        self.status.setText("Putting the new version in place…")
        try:
            how = self._facade.install_update(new_file)
        except GeeAssistError as exc:
            self._failed(exc)
            return
        self.state = "done"
        if how == "swapped":
            self.status.setText("Updated. Restarting GEE-Assist…")
            QProcess.startDetached(self._facade.app_executable(), [])
        else:
            self.status.setText("Updated with administrator rights. GEE-Assist restarts in a moment…")
        QTimer.singleShot(400, QApplication.quit)

    def _failed(self, exc: Exception) -> None:
        self._timer.stop()
        self.state = "failed"
        self.bar.hide()
        self.update_button.setEnabled(True)
        self.update_button.setText("Try again")
        self.later_button.setText("Quit GEE-Assist" if self.forced else "Later")
        message = str(exc) if isinstance(exc, GeeAssistError) else f"The update failed: {exc}"
        if isinstance(exc, UpdateError) and exc.web_page:
            message += " Use “Open download page” to get it from the website."
        self.status.setText(message + " Your current version still works.")

    def _later(self) -> None:
        if self.state == "downloading":
            self._progress.cancel.set()
            self.status.setText("Cancelling…")
            return
        if self.forced:
            QApplication.quit()
        self.reject()

    def open_page(self) -> None:
        if self.info.download_url:
            QDesktopServices.openUrl(QUrl(self.info.download_url))
        if not self.forced:
            self.accept()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API) - closing a required update quits the app
        if self.state in ("downloading", "installing"):
            event.ignore()
            return
        if self.forced and self.state != "done":
            QApplication.quit()
        super().closeEvent(event)
