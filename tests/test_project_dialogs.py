"""Project dialogs and ProjectActions against a real RequestService on temporary folders (offscreen)."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication, QDialog, QWidget  # noqa: E402

from backend.business.request.request_service import RequestService  # noqa: E402
from backend.data.dao.project_dao import ProjectDAO  # noqa: E402
from backend.data.data_facade import DataFacade  # noqa: E402
from frontend.views.project_dialogs import NewProjectDialog, ProjectActions, RenameProjectDialog  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class Facade:
    """The project part of the business facade, on a real RequestService."""

    def __init__(self, tmp_path):
        data = DataFacade(gemini_client=None, project_dao=ProjectDAO(tmp_path / "projects.json"))
        self.requests = RequestService(data_facade=data)

    def suggest_project_name(self, location):
        return self.requests.suggest_project_name(location)

    def create_project(self, name, location):
        return self.requests.create_project(name, location, "u1")

    def open_project(self, folder):
        return self.requests.open_project(folder, "u1")

    def rename_project(self, name):
        return self.requests.rename_project(name)

    def move_project(self, location):
        return self.requests.move_project(location)

    def close_project(self):
        self.requests.close_project()

    def get_current_project(self):
        return self.requests.get_current_project()

    def list_projects(self, user_id=None):
        return self.requests.list_projects("u1")


def wait_until(condition, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def facade(tmp_path):
    return Facade(tmp_path)


def test_new_project_shows_where_the_folder_goes_and_creates_it(app, facade, tmp_path):
    dialog = NewProjectDialog(facade, str(tmp_path / "work"))
    dialog.fields["name"].set_text("MyProject")
    assert str(tmp_path / "work" / "MyProject") in dialog.preview.text()
    dialog.action_button.click()
    assert wait_until(lambda: dialog.result() == QDialog.DialogCode.Accepted)
    assert dialog.project.name == "MyProject" and (tmp_path / "work" / "MyProject" / "downloads").is_dir()


def test_new_project_shows_problems_under_the_field(app, facade, tmp_path):
    dialog = NewProjectDialog(facade, str(tmp_path))
    dialog.fields["name"].set_text("bad|name")
    dialog.action_button.click()
    assert wait_until(lambda: dialog.fields["name"].has_error())
    assert "cannot contain" in dialog.fields["name"].message.text() and dialog.result() == 0


def test_browse_fills_the_location(app, facade, tmp_path):
    dialog = NewProjectDialog(facade, "")
    dialog.choose_folder = lambda: str(tmp_path / "picked")
    dialog.browse_button.click()
    assert dialog.fields["location"].text() == str(tmp_path / "picked")


def test_rename_dialog(app, facade, tmp_path):
    project = facade.create_project("Old", str(tmp_path))
    dialog = RenameProjectDialog(facade, project)
    dialog.fields["name"].set_text("New")
    dialog.action_button.click()
    assert wait_until(lambda: dialog.result() == QDialog.DialogCode.Accepted)
    assert dialog.project.name == "New" and (tmp_path / "New").is_dir()


@pytest.fixture
def actions(app, facade):
    window = QWidget()
    actions = ProjectActions(facade, window)
    actions.changes = []
    actions.warnings = []
    actions.project_changed.connect(actions.changes.append)
    actions.warn = lambda title, text: actions.warnings.append(text)
    actions.confirm = lambda title, text: True
    yield actions
    window.deleteLater()


def test_open_close_and_reopen_a_project(actions, facade, tmp_path):
    project = facade.create_project("Work", str(tmp_path))
    actions.close_project()
    assert facade.get_current_project() is None and actions.changes == [None]
    actions.choose_folder = lambda title, start: project.folder
    assert actions.open_project().id == project.id
    assert actions.changes[-1].id == project.id


def test_opening_a_folder_that_is_not_a_project_warns(actions, tmp_path):
    assert actions.open_folder(str(tmp_path)) is None
    assert "not a GEE-Assist project" in actions.warnings[0] and actions.changes == []


def test_move_project_after_confirming(actions, facade, tmp_path):
    facade.create_project("Travel", str(tmp_path / "a"))
    actions.choose_folder = lambda title, start: str(tmp_path / "b")
    actions.move_project()
    assert wait_until(lambda: actions.changes)
    assert (tmp_path / "b" / "Travel" / "project.json").is_file()


def test_move_can_be_cancelled(actions, facade, tmp_path):
    facade.create_project("Stay", str(tmp_path / "a"))
    actions.choose_folder = lambda title, start: str(tmp_path / "b")
    actions.confirm = lambda title, text: False
    actions.move_project()
    assert (tmp_path / "a" / "Stay").is_dir() and actions.changes == []


def test_new_projects_are_suggested_next_to_the_last_one(actions, facade, tmp_path):
    facade.create_project("First", str(tmp_path / "projects"))
    assert actions.default_location() == str((tmp_path / "projects").resolve())


def test_an_empty_name_shows_and_uses_the_next_project_number(app, facade, tmp_path):
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "Project 1").mkdir()
    dialog = NewProjectDialog(facade, str(tmp_path / "work"))
    assert dialog.fields["name"].input.placeholderText() == "Project 2"
    assert str(tmp_path / "work" / "Project 2") in dialog.preview.text()
    dialog.action_button.click()
    assert wait_until(lambda: dialog.result() == QDialog.DialogCode.Accepted)
    assert dialog.project.name == "Project 2" and (tmp_path / "work" / "Project 2" / "downloads").is_dir()
