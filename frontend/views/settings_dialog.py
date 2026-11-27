"""The user's own settings: Earth Engine project, Gemini API key and how long "Keep me signed in" lasts.

Shown once at the first sign-in of a new copy (both values are needed, and it says how to get them),
and from Options > Settings… afterwards.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QKeyEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from backend.business.facade import IBusinessFacade
from backend.business.settings.settings_rules import SESSION_CHOICES
from backend.dto.settings_dto import AppSettingsDTO, AppSettingsUpdateDTO
from backend.dto.validation_dto import ValidationDTO
from backend.exceptions import GeeAssistError
from frontend import theme
from frontend.widgets.form_widgets import Banner, BusyButton, FormField, PasswordField, link_button
from frontend.workers.task_worker import run_task

GEE_STEPS = """
<ol style="margin-left:-20px">
<li>Open the <a href="https://console.cloud.google.com/projectcreate">Google Cloud console</a> with your Google
account and create a project (or choose one you have). Note its <b>Project ID</b>, e.g.
<i>my-gee-project-123</i>: shown under the name, not the name itself.</li>
<li>Register the project for Earth Engine at
<a href="https://code.earthengine.google.com/register">code.earthengine.google.com/register</a>: choose
<i>Unpaid usage</i> (research or education) and pick your project.</li>
<li>Turn on the <a href="https://console.cloud.google.com/apis/library/earthengine.googleapis.com">Earth Engine
API</a> for that project (press <b>Enable</b>).</li>
<li>Enter the Project ID here. Then sign this computer in to Earth Engine once:
<b>Terminal → Sign in to Earth Engine…</b></li>
</ol>"""

GEMINI_STEPS = """
<ol style="margin-left:-20px">
<li>Open <a href="https://aistudio.google.com/apikey">Google AI Studio</a> and sign in with your Google account.</li>
<li>Press <b>Create API key</b> (choose or create a Google Cloud project when asked).</li>
<li>Copy the key (it usually starts with <i>AIza</i>) and paste it here.</li>
</ol>
<p>Keep the key to yourself: it is stored in this computer's credential store (Windows Credential Manager),
never in a plain file.</p>"""


def duration_label(seconds: float) -> str:
    days = seconds / 86400
    if days >= 1 and days.is_integer():
        return f"{int(days)} day{'s' if days != 1 else ''}"
    hours = seconds / 3600
    if hours >= 1 and hours.is_integer():
        return f"{int(hours)} hour{'s' if hours != 1 else ''}"
    return f"{int(seconds // 60)} minutes"


class StepsView(QTextBrowser):
    """Rich text with working web links, exactly as tall as its text (a label would cut long steps off)."""

    def __init__(self, html: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(f"QTextBrowser {{ background: {theme.FOAM}; border: 1px solid {theme.BORDER};"
                           f" border-radius: 8px; padding: 4px 6px; color: {theme.MUTED}; }}")
        self.setHtml(html)

    def text(self) -> str:
        return self.toHtml()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._fit()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        self._fit()

    def _fit(self) -> None:
        self.document().setTextWidth(self.viewport().width())
        height = int(self.document().size().height()) + self.frameWidth() * 2 + 12
        if height != self.height():
            self.setFixedHeight(height)


class HelpSteps(QWidget):
    """A "How do I get one?" link that folds out numbered steps with web links."""

    toggled = pyqtSignal()

    def __init__(self, link_text: str, steps_html: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.toggle = link_button(link_text)
        self.steps = StepsView(steps_html)
        self.steps.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.steps)
        self.toggle.clicked.connect(self.flip)

    def flip(self) -> None:
        self.steps.setVisible(not self.steps.isVisible())
        self.toggled.emit()


class SettingsDialog(QDialog):
    sign_out_requested = pyqtSignal()  # first run only: the way out without entering the settings

    def __init__(self, facade: IBusinessFacade, first_run: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._facade = facade
        self._first_run = first_run
        self.result_message = ""
        settings = facade.get_app_settings()
        self.setWindowTitle("Set up GEE-Assist" if first_run else "Settings")
        self.setFixedWidth(620)  # a known width, so the wrapped help steps get their full height
        self.setStyleSheet(
            f"QDialog {{ background: {theme.WHITE}; }}"
            f"QComboBox {{ background: {theme.FIELD_BG}; border: 1px solid {theme.BORDER_STRONG};"
            f" border-radius: 8px; padding: 8px 10px; }}"
        )

        heading = QLabel("Set up GEE-Assist" if first_run else "Settings")
        heading.setStyleSheet(f"font-family: '{theme.SERIF}'; font-size: 16.2pt; color: {theme.INK};")
        intro = QLabel(
            "GEE-Assist uses your own Google Earth Engine project to download datasets and your own Gemini "
            "API key to understand requests written in plain language. Enter both to start; you can change "
            "them later in Options → Settings…" if first_run else
            "Your Earth Engine project, Gemini API key and how long you stay signed in. Changes are used at once.",
            objectName="Muted",
        )
        intro.setWordWrap(True)
        self.banner = Banner()

        self.project_field = FormField("Earth Engine project ID", "e.g. my-gee-project-123",
                                       "The Google Cloud project registered for Earth Engine")
        self.project_field.set_text(settings.gee_project)
        self.project_help = HelpSteps("How do I get my project ID?", GEE_STEPS)

        key_hint = (f"A key is saved ({settings.gemini_key_hint}). Leave empty to keep it, or paste a new one."
                    if settings.gemini_key_set else "Used to fill the request form from what you write")
        self.key_field = PasswordField("Gemini API key", "Paste your key (it usually starts with AIza)", key_hint)
        self.key_help = HelpSteps("How do I get a Gemini API key?", GEMINI_STEPS)

        self.session_box = QComboBox()
        for label, seconds in SESSION_CHOICES:
            self.session_box.addItem(label, seconds)
        index = self.session_box.findData(float(settings.session_duration))
        if index < 0:  # a length set in .env that is not in the list
            self.session_box.addItem(duration_label(settings.session_duration), float(settings.session_duration))
            index = self.session_box.count() - 1
        self.session_box.setCurrentIndex(index)
        session_label = QLabel("Keep me signed in for", objectName="FieldLabel")
        session_hint = QLabel("When you tick \"Keep me signed in\". Applies from your next sign-in.",
                              objectName="FieldHint")
        session_hint.setWordWrap(True)
        self.session_error = QLabel(objectName="FieldError")
        self.session_error.hide()

        self.save_button = BusyButton("Save and continue" if first_run else "Save", "Saving…")
        self.save_button.setDefault(True)
        self.other_button = QPushButton("Sign out" if first_run else "Cancel", objectName="SecondaryButton")
        self.other_button.setCursor(Qt.CursorShape.PointingHandCursor)
        buttons = QHBoxLayout()
        if first_run:
            buttons.addWidget(self.other_button)
            buttons.addStretch(1)
        else:
            buttons.addStretch(1)
            buttons.addWidget(self.other_button)
        buttons.addWidget(self.save_button)

        # The form scrolls when the help steps make it taller than the screen; the buttons always show.
        content = QWidget()
        form = QVBoxLayout(content)
        form.setContentsMargins(28, 24, 28, 8)
        form.setSpacing(10)
        form.addWidget(heading)
        form.addWidget(intro)
        form.addWidget(self.banner)
        form.addSpacing(4)
        form.addWidget(self.project_field)
        form.addWidget(self.project_help)
        form.addSpacing(6)
        form.addWidget(self.key_field)
        form.addWidget(self.key_help)
        form.addSpacing(6)
        form.addWidget(session_label)
        form.addWidget(self.session_box)
        form.addWidget(session_hint)
        form.addWidget(self.session_error)
        form.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(content)
        self._content = content

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 22)
        layout.setSpacing(12)
        layout.addWidget(self.scroll, 1)
        button_row = QHBoxLayout()
        button_row.setContentsMargins(28, 0, 28, 0)
        button_row.addLayout(buttons)
        layout.addLayout(button_row)
        for help_steps in (self.project_help, self.key_help):
            help_steps.toggled.connect(self.fit_to_screen)

        self.fields = {"gee_project": self.project_field, "gemini_api_key": self.key_field}
        for field in self.fields.values():
            field.input.returnPressed.connect(self.save)
        self.save_button.clicked.connect(self.save)
        self.other_button.clicked.connect(self._sign_out if first_run else self.reject)
        if first_run:
            for help_steps in (self.project_help, self.key_help):  # first time: the steps are what is needed
                help_steps.steps.show()
        (self.key_field if settings.gee_project and not settings.gemini_key_set else self.project_field).input.setFocus()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        self.fit_to_screen()

    def fit_to_screen(self) -> None:
        """As tall as the form, up to 90% of the screen (then the form scrolls)."""
        self._content.adjustSize()
        wanted = self._content.sizeHint().height() + 12 + self.save_button.sizeHint().height() + 22
        screen = self.screen().availableGeometry().height() if self.screen() else 900
        self.resize(self.width(), min(wanted, int(screen * 0.9)))

    # ------------------------------------------------------------- saving
    def entered_settings(self) -> AppSettingsUpdateDTO:
        return AppSettingsUpdateDTO(gee_project=self.project_field.text(), gemini_api_key=self.key_field.text(),
                                    session_duration=float(self.session_box.currentData()))

    def save(self) -> None:
        if not self.save_button.isEnabled():
            return
        self.banner.clear()
        for field in self.fields.values():
            field.clear_error()
        self.session_error.hide()
        self.save_button.set_busy(True)
        run_task(self, self._facade.save_app_settings, self.entered_settings(), on_success=self._on_saved,
                 on_error=self._on_failed)

    def _on_saved(self, result: ValidationDTO) -> None:
        self.save_button.set_busy(False)
        if result.is_valid:
            self.result_message = result.message
            self._first_run = False  # may close now
            self.accept()
            return
        elsewhere = []
        for key, message in result.errors.items():
            if key in self.fields:
                self.fields[key].set_error(message)
            elif key == "session_duration":
                self.session_error.setText(message)
                self.session_error.show()
            else:
                elsewhere.append(message)
        if elsewhere:
            self.banner.show_error(" ".join(elsewhere))

    def _on_failed(self, exc: Exception) -> None:
        self.save_button.set_busy(False)
        self.banner.show_error(str(exc) if isinstance(exc, GeeAssistError) else "The settings could not be saved.")

    # ------------------------------------------------------------- first run: no way round it but signing out
    def _sign_out(self) -> None:
        self._first_run = False
        self.sign_out_requested.emit()
        self.reject()

    def reject(self) -> None:
        if not self._first_run:
            super().reject()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt API)
        if self._first_run and event.key() == Qt.Key.Key_Escape:
            return
        super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt API)
        if self._first_run:
            event.ignore()
            return
        super().closeEvent(event)


def settings_needed(facade: IBusinessFacade) -> list[str]:
    """What a new copy still needs before it can be used ("gee_project", "gemini_api_key")."""
    try:
        settings = facade.get_app_settings()
    except GeeAssistError:
        return []
    return settings.missing if isinstance(settings, AppSettingsDTO) else []
