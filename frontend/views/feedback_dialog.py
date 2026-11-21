"""Ask the user to rate GEE-Assist, send feedback or suggest a feature.

The choice opens the matching tab of the website's community page in the browser,
e.g. ``https://gee-assist-web.vercel.app/community?tab=feedback`` (the address is ``WEB_APP_URL``).
The tabs are the website's: ``rate``, ``feedback`` and ``suggest``.
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from backend.config.settings import get_settings
from frontend import theme

RATE, FEEDBACK, SUGGEST = "rate", "feedback", "suggest"

# Website tab -> (button title, what it is for, icon). Titles are the website's tab names.
CHOICES: dict[str, tuple[str, str, str]] = {
    RATE: ("Rate the app", "Give GEE-Assist one to five stars.", "★"),
    FEEDBACK: ("Send feedback", "Report a bug, a confusing screen or something slow.", "✉"),
    SUGGEST: ("Suggest a feature", "Tell us what to build next.", "✦"),
}

STYLESHEET = f"""
QDialog {{ background: {theme.WHITE}; }}
QLabel#FeedbackTitle {{ font-family: "{theme.SERIF}"; font-size: 16pt; color: {theme.INK}; }}
QPushButton#FeedbackChoice {{
    background: {theme.FIELD_BG}; border: 1px solid {theme.BORDER}; border-radius: 10px;
    padding: 12px 14px; text-align: left; color: {theme.INK};
}}
QPushButton#FeedbackChoice:hover {{ background: {theme.MINT}; border-color: {theme.BORDER_HOVER}; }}
QPushButton#FeedbackChoice:focus {{ border-color: {theme.LEAF}; }}
"""

UrlOpener = Callable[[QUrl], bool]


def community_url(tab: str, base_url: str | None = None) -> str:
    """The website's community page opened on ``tab`` ("rate", "feedback" or "suggest")."""
    if tab not in CHOICES:
        raise ValueError(f"Unknown community tab {tab!r}")
    base = (base_url if base_url is not None else get_settings().web_app_url).rstrip("/")
    return f"{base}/community?tab={tab}"


class FeedbackDialog(QDialog):
    """A modal with three choices; choosing one opens its community tab in the browser."""

    def __init__(self, parent: QWidget | None = None, reason: str = "", open_url: UrlOpener | None = None,
                 base_url: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Help us improve GEE-Assist")
        self.setModal(True)
        self.setMinimumWidth(440)
        self.setStyleSheet(STYLESHEET)
        self._open_url = open_url or QDesktopServices.openUrl
        self._base_url = base_url
        self.choice: str | None = None
        self.opened_url = ""

        title = QLabel("How is GEE-Assist working for you?", objectName="FeedbackTitle")
        title.setWordWrap(True)
        hint = QLabel((reason + " " if reason else "") +
                      "Tell us on the GEE-Assist website: it opens in your browser.", objectName="Muted")
        hint.setWordWrap(True)

        self.buttons: dict[str, QPushButton] = {}
        choices = QVBoxLayout()
        choices.setSpacing(8)
        for tab, (label, blurb, icon) in CHOICES.items():
            button = QPushButton(f"{icon}   {label}\n      {blurb}", objectName="FeedbackChoice")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(community_url(tab, base_url))
            button.clicked.connect(lambda _=False, chosen=tab: self.choose(chosen))
            choices.addWidget(button)
            self.buttons[tab] = button

        self.not_now = QPushButton("Not now", objectName="SecondaryButton")
        self.not_now.setCursor(Qt.CursorShape.PointingHandCursor)
        self.not_now.clicked.connect(self.reject)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(self.not_now)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addLayout(choices)
        layout.addLayout(footer)

    def choose(self, tab: str) -> None:
        """Open the community page on ``tab`` and close."""
        self.choice = tab
        self.opened_url = community_url(tab, self._base_url)
        self._open_url(QUrl(self.opened_url))
        self.accept()


def ask_for_feedback(parent: QWidget | None = None, reason: str = "",
                     open_url: UrlOpener | None = None) -> str | None:
    """Show the modal; the tab opened ("rate", "feedback", "suggest"), or None for "Not now"."""
    dialog = FeedbackDialog(parent, reason, open_url)
    dialog.exec()
    return dialog.choice
