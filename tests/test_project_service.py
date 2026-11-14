"""RequestService's projects: create, open, rename, move, history and analysis results (real folders)."""

import json
from types import SimpleNamespace

import pytest

from backend.business.request.project_rules import project_name_error
from backend.business.request.request_service import RequestService
from backend.data.dao.project_dao import ProjectDAO
from backend.data.data_facade import DataFacade
from backend.exceptions import ProjectError


@pytest.fixture
def service(tmp_path):
    facade = DataFacade(gemini_client=None, project_dao=ProjectDAO(tmp_path / "workspace" / "projects.json"))
    return RequestService(data_facade=facade)


@pytest.fixture
def work(tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    return folder


@pytest.mark.parametrize(("name", "ok"), [
    ("MyProject", True), ("Lahore NDVI 2024", True), ("", False), ("   ", False), ("a/b", False),
    ('bad"name', False), ("ends.", False), ("CON", False), ("com1.txt", False), ("x" * 81, False),
])
def test_project_names_must_be_folder_names(name, ok):
    assert (project_name_error(name) is None) == ok


def test_create_makes_the_folders_and_opens_the_project(service, work):
    project = service.create_project("  My   Project ", str(work), owner_id="u1")
    folder = work / "My Project"
    assert project.name == "My Project" and project.folder == str(folder.resolve())
    assert (folder / "downloads").is_dir() and (folder / "analysis").is_dir() and (folder / "project.json").is_file()
    assert service.get_current_project() == project
    assert project.downloads_dir == str(folder.resolve() / "downloads")


def test_create_makes_a_missing_location(service, work):
    project = service.create_project("P", str(work / "new" / "place"))
    assert (work / "new" / "place" / "P" / "downloads").is_dir() and service.get_current_project() == project


@pytest.mark.parametrize(("name", "location", "field"), [("bad|name", "work", "name"), ("Fine", "", "location")])
def test_create_points_at_the_wrong_field(service, work, name, location, field):
    with pytest.raises(ProjectError) as caught:
        service.create_project(name, str(work) if location else "")
    assert caught.value.field == field and service.get_current_project() is None


def test_create_refuses_an_existing_project_or_a_folder_with_files(service, work):
    service.create_project("Taken", str(work))
    with pytest.raises(ProjectError, match="Open it instead"):
        service.create_project("Taken", str(work))
    (work / "Busy").mkdir()
    (work / "Busy" / "notes.txt").write_text("x")
    with pytest.raises(ProjectError, match="already exists"):
        service.create_project("Busy", str(work))
    (work / "Empty").mkdir()
    assert service.create_project("Empty", str(work)).name == "Empty"  # an empty folder is fine


def test_open_an_existing_project_and_list_the_recent_ones(service, work):
    first = service.create_project("First", str(work), owner_id="u1")
    service.create_project("Second", str(work), owner_id="u1")
    service.close_project()
    opened = service.open_project(first.folder, owner_id="u1")
    assert opened.id == first.id and service.get_current_project() == opened
    assert [p.name for p in service.list_projects("u1")] == ["First", "Second"]  # most recently opened first
    assert service.list_projects("someone else") == []


def test_open_refuses_folders_that_are_not_projects(service, work):
    with pytest.raises(ProjectError, match="not a GEE-Assist project"):
        service.open_project(str(work))
    with pytest.raises(ProjectError, match="no longer exists"):
        service.open_project(str(work / "missing"))


def test_projects_whose_folder_is_gone_are_not_listed(service, work):
    import shutil

    gone = service.create_project("Gone", str(work), owner_id="u1")
    service.create_project("Here", str(work), owner_id="u1")
    shutil.rmtree(gone.folder)
    assert [p.name for p in service.list_projects("u1")] == ["Here"]


def test_rename_renames_the_folder(service, work):
    service.create_project("Old Name", str(work))
    (work / "Old Name" / "downloads" / "data.tif").write_bytes(b"tif")
    renamed = service.rename_project("New Name")
    assert renamed.name == "New Name" and (work / "New Name" / "downloads" / "data.tif").exists()
    assert not (work / "Old Name").exists() and service.get_current_project() == renamed
    assert json.loads((work / "New Name" / "project.json").read_text())["name"] == "New Name"


def test_rename_to_a_taken_name_or_only_changing_the_case(service, work):
    service.create_project("Other", str(work))
    service.create_project("mine", str(work))
    with pytest.raises(ProjectError, match="Open it instead"):
        service.rename_project("Other")
    assert service.rename_project("Mine").name == "Mine"
    assert sorted(p.name for p in work.iterdir()) == ["Mine", "Other"]


def test_move_moves_the_folder(service, work):
    service.create_project("Travel", str(work / "a"))
    moved = service.move_project(str(work / "b"))
    assert (work / "b" / "Travel" / "project.json").exists() and not (work / "a" / "Travel").exists()
    assert moved.location == str((work / "b").resolve())


def test_move_refuses_its_own_folder_and_taken_places(service, work):
    project = service.create_project("Here", str(work))
    with pytest.raises(ProjectError, match="its own folder"):
        service.move_project(str(work / "Here" / "downloads"))
    (work / "elsewhere" / "Here").mkdir(parents=True)
    (work / "elsewhere" / "Here" / "x.txt").write_text("x")
    with pytest.raises(ProjectError, match="already exists"):
        service.move_project(str(work / "elsewhere"))
    assert service.move_project(str(work)) == project  # already there: nothing to do


def test_renaming_or_moving_needs_an_open_project(service):
    with pytest.raises(ProjectError, match="Create or open a project"):
        service.rename_project("X")
    with pytest.raises(ProjectError, match="Create or open a project"):
        service.move_project("somewhere")


def test_analysis_results_are_recorded_in_the_open_project(service, work):
    project = service.create_project("Results", str(work))
    result = SimpleNamespace(id="r1", category="water", processes=["NDWI"], metrics={"Water area (km²)": 3.1},
                             output_path=str(work / "Results" / "analysis" / "water.tif"), saved=True,
                             created_at="2026-11-14T12:00:00", device="CPU", seconds=2.0, notes=[], dataset=None)
    record = service.record_analysis_result(result)
    assert record.output_path == "analysis/water.tif"
    assert service.get_analysis_results(project) == [record]
    stored = json.loads((work / "Results" / "analysis" / "analysis_results.json").read_text())
    assert stored["results"][0]["category"] == "water"
    service.close_project()
    with pytest.raises(ProjectError):
        service.record_analysis_result(result)
