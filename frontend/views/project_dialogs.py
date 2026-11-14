"""Creating, opening, renaming, moving and closing projects.

``ProjectActions`` is used by both the dashboard and the File menu: it asks what it needs (a name,
a folder), calls the facade and announces the open project with ``project_changed``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QObject, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from backend.business.facade import IBusinessFacade
from backend.config.settings import DEFAULT_PROJECTS_DIR
from backend.dto.project_dto import ProjectDTO
from backend.exceptions import GeeAssistError, ProjectError
from frontend import theme
from frontend.widgets.form_widgets import Banner, BusyButton, FormField
from frontend.workers.task_worker import run_task


class ProjectDialog(QDialog):
    """A titled form with a banner and Cancel / action buttons; ``_submit`` runs the action."""

    def __init__(self, facade: IBusinessFacade, title: str, subtitle: str, action: str, busy: str,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._facade = facade
        self.project: ProjectDTO | None = None  # the project once the action succeeded
        self.fields: dict[str, FormField] = {}
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        self.setStyleSheet(f"QDialog {{ background: {theme.WHITE}; }}")

        heading = QLabel(title)
        heading.setStyleSheet(f"font-family: '{theme.SERIF}'; font-size: 16pt; color: {theme.INK};")
        intro = QLabel(subtitle, objectName="Muted")
        intro.setWordWrap(True)
        self.banner = Banner()
        self.form = QVBoxLayout()
        self.form.setSpacing(12)

        self.cancel_button = QPushButton("Cancel", objectName="SecondaryButton")
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.clicked.connect(self.reject)
        self.action_button = BusyButton(action, busy)
        self.action_button.setDefault(True)
        self.action_button.clicked.connect(self._submit)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.action_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(14)
        layout.addWidget(heading)
        layout.addWidget(intro)
        layout.addWidget(self.banner)
        layout.addLayout(self.form)
        layout.addSpacing(4)
        layout.addLayout(buttons)

    def add_field(self, key: str, field: FormField, value: str = "") -> FormField:
        field.set_text(value)
        field.input.returnPressed.connect(self._submit)
        self.fields[key] = field
        return field

    def _submit(self) -> None:
        raise NotImplementedError

    def _run(self, call: Callable[..., ProjectDTO], *args) -> None:
        if not self.action_button.isEnabled():
            return
        self.banner.clear()
        for field in self.fields.values():
            field.clear_error()
        self.action_button.set_busy(True)
        run_task(self, call, *args, on_success=self._on_done, on_error=self._on_error)

    def _on_done(self, project: ProjectDTO) -> None:
        self.action_button.set_busy(False)
        self.project = project
        self.accept()

    def _on_error(self, exc: Exception) -> None:
        self.action_button.set_busy(False)
        field = getattr(exc, "field", None)
        if isinstance(exc, ProjectError) and field in self.fields:
            self.fields[field].set_error(str(exc))
            self.fields[field].input.setFocus()
        else:
            self.banner.show_error(str(exc) if isinstance(exc, GeeAssistError) else "Something went wrong.")


class NewProjectDialog(ProjectDialog):
    """Name and parent folder; the project is the folder ``<location>/<name>``."""

    def __init__(self, facade: IBusinessFacade, location: str, parent: QWidget | None = None):
        super().__init__(facade, "New project",
                         "A project is a folder for your work: downloaded datasets go into its downloads "
                         "folder and analysis results into its analysis folder.",
                         "Create project", "Creating…", parent)
        name = self.add_field("name", FormField("Project name", "e.g. Lahore vegetation 2024"))
        self.form.addWidget(name)
        location_field = self.add_field("location", FormField("Location", "Folder to create the project in"),
                                        location)
        self.browse_button = QPushButton("Browse…", objectName="SecondaryButton")
        self.browse_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse_button.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(location_field, 1)
        row.addWidget(self.browse_button, 0, Qt.AlignmentFlag.AlignBottom)
        self.form.addLayout(row)
        self.preview = QLabel(objectName="FieldHint")
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.form.addWidget(self.preview)
        for field in self.fields.values():
            field.input.textChanged.connect(self._update_preview)
        self._update_preview()
        name.input.setFocus()

    def choose_folder(self) -> str:
        return QFileDialog.getExistingDirectory(self, "Create the project in", self.fields["location"].text())

    def _browse(self) -> None:
        folder = self.choose_folder()
        if folder:
            self.fields["location"].set_text(str(Path(folder)))

    def _update_preview(self) -> None:
        name = " ".join(self.fields["name"].text().split())
        location = self.fields["location"].text().strip()
        self.preview.setText(f"The project folder will be:  {Path(location) / name}" if name and location else "")

    def _submit(self) -> None:
        self._run(self._facade.create_project, self.fields["name"].text(), self.fields["location"].text())


class RenameProjectDialog(ProjectDialog):
    def __init__(self, facade: IBusinessFacade, project: ProjectDTO, parent: QWidget | None = None):
        super().__init__(facade, "Rename project", f"The folder {project.folder} is renamed too.",
                         "Rename", "Renaming…", parent)
        self.form.addWidget(self.add_field("name", FormField("Project name"), project.name))
        self.fields["name"].input.selectAll()
        self.fields["name"].input.setFocus()

    def _submit(self) -> None:
        self._run(self._facade.rename_project, self.fields["name"].text())


class ProjectActions(QObject):
    """What the dashboard and the File menu do with projects."""

    project_changed = pyqtSignal(object)  # the open ProjectDTO, or None after closing

    def __init__(self, facade: IBusinessFacade, window: QWidget):
        super().__init__(window)
        self._facade = facade
        self._window = window

    # ------------------------------------------------------------- asking the user (replaced in tests)
    def choose_folder(self, title: str, start: str) -> str:
        return QFileDialog.getExistingDirectory(self._window, title, start)

    def confirm(self, title: str, text: str) -> bool:
        answer = QMessageBox.question(self._window, title, text,
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Yes)
        return answer == QMessageBox.StandardButton.Yes

    def warn(self, title: str, text: str) -> None:
        QMessageBox.warning(self._window, title, text)

    def exec_dialog(self, dialog: ProjectDialog) -> ProjectDTO | None:
        return dialog.project if dialog.exec() == QDialog.DialogCode.Accepted else None

    # ------------------------------------------------------------- actions
    def new_project(self) -> ProjectDTO | None:
        project = self.exec_dialog(NewProjectDialog(self._facade, self.default_location(), self._window))
        if project is not None:
            self.project_changed.emit(project)
        return project

    def open_project(self) -> ProjectDTO | None:
        current = self._facade.get_current_project()
        start = current.location if current is not None else self.default_location()
        folder = self.choose_folder("Open project folder", start)
        return self.open_folder(folder) if folder else None

    def open_folder(self, folder: str) -> ProjectDTO | None:
        """Open the project in ``folder`` (e.g. one of the recent projects)."""
        try:
            project = self._facade.open_project(folder)
        except GeeAssistError as exc:
            self.warn("Open project", str(exc))
            return None
        self.project_changed.emit(project)
        return project

    def rename_project(self) -> ProjectDTO | None:
        current = self._facade.get_current_project()
        if current is None:
            return None
        project = self.exec_dialog(RenameProjectDialog(self._facade, current, self._window))
        if project is not None:
            self.project_changed.emit(project)
        return project

    def move_project(self) -> None:
        current = self._facade.get_current_project()
        if current is None:
            return
        location = self.choose_folder(f"Move {current.name} to", current.location)
        if not location or Path(location).resolve() == Path(current.location).resolve():
            return
        target = Path(location) / current.name
        if not self.confirm("Move project", f"Move the project folder to\n{target}?\n\n"
                                            "Everything in it moves too: downloads and analysis results."):
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)  # a folder of big GeoTIFFs takes a while
        run_task(self, self._facade.move_project, location, on_success=self._on_moved, on_error=self._on_move_failed)

    def _on_moved(self, project: ProjectDTO) -> None:
        QApplication.restoreOverrideCursor()
        self.project_changed.emit(project)

    def _on_move_failed(self, exc: Exception) -> None:
        QApplication.restoreOverrideCursor()
        self.warn("Move project", str(exc) if isinstance(exc, GeeAssistError) else "The project could not be moved.")

    def close_project(self) -> None:
        self._facade.close_project()
        self.project_changed.emit(None)

    def show_project_folder(self) -> None:
        current = self._facade.get_current_project()
        if current is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(current.folder))

    def default_location(self) -> str:
        """Where the last project is, else Documents/GEE-Assist Projects."""
        try:
            recent = self._facade.list_projects()
        except GeeAssistError:
            recent = []
        if recent and isinstance(recent[0], ProjectDTO):
            return recent[0].location
        return str(DEFAULT_PROJECTS_DIR)
