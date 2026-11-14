"""Projects end to end: BusinessFacade -> RequestService / DownloadService -> ProjectDAO, on real folders.

Only Earth Engine is faked (it writes small GeoTIFFs); everything else is the real code.
"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("rasterio")

from backend.business.download import Chunker, ChunkMerger, DownloadService  # noqa: E402
from backend.business.download.job_store import DownloadJobStore  # noqa: E402
from backend.business.facade import BusinessFacade  # noqa: E402
from backend.business.request.request_service import RequestService  # noqa: E402
from backend.config.download_settings import DownloadSettings, DownloadSettingsStore  # noqa: E402
from backend.data.dao.project_dao import ProjectDAO  # noqa: E402
from backend.data.data_facade import DataFacade  # noqa: E402
from backend.dto.download_dto import JOB_COMPLETED  # noqa: E402
from backend.exceptions import ProjectError  # noqa: E402
from tests.test_download_service import FakeData, _form, _wait  # noqa: E402


@pytest.fixture
def app(tmp_path):
    settings = DownloadSettingsStore(tmp_path / "download_settings.json")
    settings.save(DownloadSettings(chunk_size_mb=1, retry_limit=1))
    downloads = DownloadService(FakeData(), Chunker(settings), ChunkMerger(), tmp_path / "unused",
                                job_store=DownloadJobStore(tmp_path / "download_jobs.json"),
                                settings=settings, retry_delay=0.01)
    requests = RequestService(data_facade=DataFacade(gemini_client=None,
                                                     project_dao=ProjectDAO(tmp_path / "projects.json")))
    users = MagicMock()
    users.current_user = SimpleNamespace(id="u1")
    analysis = MagicMock()
    facade = BusinessFacade(user_service=users, request_service=requests, download_service=downloads,
                            map_service=MagicMock(), analysis_service=analysis)
    yield facade, analysis, tmp_path
    downloads.shutdown(timeout=2)


def test_a_project_holds_its_downloads_and_analysis_results_and_keeps_them_when_renamed(app):
    facade, analysis, tmp_path = app
    with pytest.raises(ProjectError):
        facade.start_download(_form(tmp_path))  # no project yet

    project = facade.create_project("MyProject", str(tmp_path / "work"))
    job = _wait(facade._download_service, facade.start_download(_form(tmp_path)), JOB_COMPLETED)
    downloads = (tmp_path / "work" / "MyProject" / "downloads").resolve()
    assert Path(job.dataset.path).parent.parent == downloads  # <project>/downloads/<dataset>/<dataset>.tif

    analysis.run_analysis.return_value = SimpleNamespace(
        id="r1", category="Vegetation", processes=["NDVI"], metrics={"NDVI mean": 0.5}, output_path="",
        saved=False, created_at="2026-11-14T12:00:00", device="CPU", seconds=1.0, notes=[], dataset=job.dataset)
    facade.run_analysis(job.dataset, "request")
    records = facade.get_analysis_results(project)
    assert [r.id for r in records] == ["r1"] and records[0].dataset.startswith("downloads/")

    renamed = facade.rename_project("Renamed")
    moved_job = facade.get_download_progress(job)
    assert Path(moved_job.dataset.path).exists() and "Renamed" in Path(moved_job.dataset.path).parts
    assert facade.get_analysis_results(renamed)[0].id == "r1"  # the JSON moved with the folder
    history = json.loads((tmp_path / "projects.json").read_text())
    assert [p["name"] for p in history["projects"]] == ["Renamed"]
    assert [p.name for p in facade.list_projects()] == ["Renamed"]
