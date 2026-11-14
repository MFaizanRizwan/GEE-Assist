"""ProjectDAO: project folders, the JSON history of where they are, and analysis results in JSON."""

import json
from types import SimpleNamespace

import pytest

from backend.data.dao.project_dao import ProjectDAO
from backend.dto.download_dto import DatasetDTO
from backend.dto.project_dto import AnalysisRecordDTO, ProjectDTO, relative_to_project
from backend.exceptions import ProjectError


@pytest.fixture
def dao(tmp_path):
    return ProjectDAO(tmp_path / "workspace" / "projects.json")


def _project(tmp_path, name="MyProject", id="p1", owner="u1", opened="2026-11-14T10:00:00"):
    return ProjectDTO(id=id, name=name, folder=str(tmp_path / "work" / name), owner_id=owner,
                      created_at="2026-11-14T09:00:00", last_opened_at=opened)


def test_save_makes_the_folder_with_downloads_and_analysis(dao, tmp_path):
    project = _project(tmp_path)
    assert dao.save(project)
    folder = tmp_path / "work" / "MyProject"
    assert (folder / "downloads").is_dir() and (folder / "analysis").is_dir()
    assert json.loads((folder / "project.json").read_text())["name"] == "MyProject"
    history = json.loads((tmp_path / "workspace" / "projects.json").read_text())
    assert history["projects"][0]["folder"] == str(folder)


def test_history_lists_the_most_recently_opened_first_per_user(dao, tmp_path):
    dao.save(_project(tmp_path, "Old", "p1", opened="2026-11-01T10:00:00"))
    dao.save(_project(tmp_path, "New", "p2", opened="2026-11-14T10:00:00"))
    dao.save(_project(tmp_path, "Theirs", "p3", owner="u2", opened="2026-11-15T10:00:00"))
    assert [p.name for p in dao.find_by_user_id("u1")] == ["New", "Old"]
    assert [p.name for p in dao.find_all()] == ["Theirs", "New", "Old"]
    assert dao.find_by_id("p3").owner_id == "u2" and dao.find_by_id("nope") is None


def test_saving_again_updates_the_entry(dao, tmp_path):
    dao.save(_project(tmp_path))
    dao.save(_project(tmp_path, opened="2026-11-20T10:00:00"))
    assert len(dao.find_all()) == 1 and dao.find_all()[0].last_opened_at == "2026-11-20T10:00:00"


def test_delete_forgets_but_keeps_the_folder(dao, tmp_path):
    dao.save(_project(tmp_path))
    assert dao.delete("p1") and dao.find_all() == []
    assert (tmp_path / "work" / "MyProject" / "project.json").exists()
    assert not dao.delete("p1")


def test_load_folder_reads_project_json(dao, tmp_path):
    dao.save(_project(tmp_path))
    loaded = dao.load_folder(str(tmp_path / "work" / "MyProject"))
    assert (loaded.id, loaded.name, loaded.owner_id) == ("p1", "MyProject", "u1")
    assert dao.load_folder(str(tmp_path)) is None  # not a project


def test_load_folder_with_a_broken_project_file(dao, tmp_path):
    (tmp_path / "project.json").write_text("{not json")
    with pytest.raises(ProjectError):
        dao.load_folder(str(tmp_path))


def test_move_renames_the_folder_and_remembers_it(dao, tmp_path):
    project = _project(tmp_path)
    dao.save(project)
    (tmp_path / "work" / "MyProject" / "downloads" / "data.tif").write_bytes(b"tif")
    moved = dao.move(project, str(tmp_path / "elsewhere" / "Renamed"))
    assert (tmp_path / "elsewhere" / "Renamed" / "downloads" / "data.tif").read_bytes() == b"tif"
    assert not (tmp_path / "work" / "MyProject").exists()
    assert dao.find_by_id("p1").folder == moved.folder == str((tmp_path / "elsewhere" / "Renamed").resolve())


def test_move_can_change_only_the_letter_case(dao, tmp_path):
    project = _project(tmp_path, "myproject")
    dao.save(project)
    moved = dao.move(project, str(tmp_path / "work" / "MyProject"))
    assert [p.name for p in (tmp_path / "work").iterdir()] == ["MyProject"]
    assert moved.folder.endswith("MyProject")


# ------------------------------------------------------------- analysis results
def _result(id="r1", saved=False, path="", created="2026-11-14T11:00:00", dataset_path=""):
    return SimpleNamespace(id=id, category="vegetation", processes=["NDVI"], metrics={"NDVI mean": 0.42},
                           output_path=path, saved=saved, created_at=created, device="CPU", seconds=1.5,
                           notes=[], dataset=DatasetDTO(id="d", source="", path=dataset_path) if dataset_path else None)


def test_analysis_results_are_kept_in_json_newest_first(dao, tmp_path):
    project = _project(tmp_path)
    dao.save(project)
    dao.save_analysis_result(project, AnalysisRecordDTO.from_result(_result("r1"), project))
    dao.save_analysis_result(project, AnalysisRecordDTO.from_result(_result("r2", created="2026-11-14T12:00:00"),
                                                                    project))
    assert [r.id for r in dao.find_analysis_results(project)] == ["r2", "r1"]
    stored = json.loads((tmp_path / "work" / "MyProject" / "analysis" / "analysis_results.json").read_text())
    assert stored["results"][0]["metrics"] == {"NDVI mean": 0.42}


def test_saving_a_result_again_replaces_its_record(dao, tmp_path):
    project = _project(tmp_path)
    dao.save(project)
    dao.save_analysis_result(project, AnalysisRecordDTO.from_result(_result(), project))
    saved_path = str(tmp_path / "work" / "MyProject" / "analysis" / "ndvi.tif")
    dao.save_analysis_result(project, AnalysisRecordDTO.from_result(_result(saved=True, path=saved_path), project))
    records = dao.find_analysis_results(project)
    assert len(records) == 1 and records[0].saved and records[0].output_path == "analysis/ndvi.tif"


def test_paths_inside_the_project_are_relative_and_others_stay(tmp_path):
    project = _project(tmp_path)
    inside = str(tmp_path / "work" / "MyProject" / "downloads" / "x.tif")
    assert relative_to_project(inside, project) == "downloads/x.tif"
    assert relative_to_project(str(tmp_path / "other.tif"), project) == str(tmp_path / "other.tif")


def test_unreadable_files_mean_empty_lists(dao, tmp_path):
    (tmp_path / "workspace").mkdir()
    (tmp_path / "workspace" / "projects.json").write_text("broken")
    assert dao.find_all() == []
    project = _project(tmp_path)
    (tmp_path / "work" / "MyProject" / "analysis").mkdir(parents=True)
    (tmp_path / "work" / "MyProject" / "analysis" / "analysis_results.json").write_text("broken")
    assert dao.find_analysis_results(project) == []
