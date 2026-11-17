"""Saved analysis results of a project, loaded back so they can be explained."""

from __future__ import annotations

import json
from dataclasses import asdict
from unittest.mock import MagicMock

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin  # noqa: E402

from backend.business.analysis import AnalysisService  # noqa: E402
from backend.business.facade import BusinessFacade  # noqa: E402
from backend.dto.project_dto import ProjectDTO  # noqa: E402
from backend.dto.result_dto import ResultLayerDTO  # noqa: E402

DATASET = "Sentinel-2_73.0250_31.0800_2024-06-01_2024-06-30"
NDVI = ResultLayerDTO("NDVI", "NDVI", "vegetation", "", -0.2, 0.8)


def write_tif(path, bands: dict) -> str:
    arrays = list(bands.values())
    height, width = arrays[0].shape
    with rasterio.open(path, "w", driver="GTiff", width=width, height=height, count=len(arrays), dtype="float32",
                       crs="EPSG:4326", transform=from_origin(73.0, 31.1, 0.001, 0.001), nodata=-9999.0) as dst:
        for index, (name, data) in enumerate(bands.items(), start=1):
            dst.write(data.astype("float32"), index)
            dst.set_band_description(index, name)
    return str(path)


def save_result(folder, name: str, created_at: str, dataset: str, summary: bool = True) -> str:
    tif = write_tif(folder / f"{name}.tif", {"NDVI": np.full((10, 12), 0.4)})
    if summary:  # as BaseAnalysis._write_summary writes it next to the GeoTIFF
        (folder / f"{name}.json").write_text(json.dumps({
            "id": f"id-{name}", "category": "Vegetation", "processes": ["NDVI"], "created_at": created_at,
            "device": "CPU", "seconds": 1.5, "dataset": dataset, "compared_with": [], "params": {"savi_l": 0.5},
            "metrics": {"NDVI mean": 0.4}, "layers": ["NDVI"], "notes": ["Clouds masked."],
            "styles": [asdict(NDVI)],
        }))
    return tif


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "Project 1"
    (folder / "analysis").mkdir(parents=True)
    (folder / "downloads").mkdir()
    return ProjectDTO("p1", "Project 1", str(folder))


@pytest.fixture
def service():
    data = MagicMock()
    data.list_formulas.return_value = []
    data.analysis_groups.return_value = []
    return AnalysisService(data_facade=data)


def test_a_saved_result_is_loaded_with_its_settings_numbers_layers_and_dataset(service, project, tmp_path):
    dataset = write_tif(tmp_path / "Project 1" / "downloads" / f"{DATASET}.tif",
                        {"B4": np.full((10, 12), 0.1), "B8": np.full((10, 12), 0.5)})
    tif = save_result(tmp_path / "Project 1" / "analysis", "result", "2024-07-01T10:00:00", dataset)
    result = service.load_result(tif)

    assert result.saved and result.output_path == tif and result.id == "id-result"
    assert (result.category, result.processes) == ("Vegetation", ["NDVI"])
    assert result.metrics == {"NDVI mean": 0.4} and result.notes == ["Clouds masked."]
    assert result.layers == [NDVI] and (result.device, result.seconds) == ("CPU", 1.5)
    assert result.created_at == "2024-07-01T10:00:00"
    assert result.dataset.path == dataset and result.dataset.bands == ["B4", "B8"]
    assert result.dataset.satellite == "Sentinel-2" and result.dataset.start_date == "2024-06-01"


def test_a_result_whose_dataset_is_gone_keeps_what_its_name_tells(service, project, tmp_path):
    tif = save_result(tmp_path / "Project 1" / "analysis", "result", "2024-07-01T10:00:00",
                      f"D:/moved/{DATASET}.tif")
    dataset = service.load_result(tif).dataset
    assert dataset.name == DATASET and dataset.satellite == "Sentinel-2" and dataset.bands == []


def test_a_geotiff_without_its_settings_is_still_listed(service, project, tmp_path):
    tif = save_result(tmp_path / "Project 1" / "analysis", "plain", "", "", summary=False)
    result = service.load_result(tif)
    assert result.saved and result.id == "plain" and result.category == "" and result.dataset is None
    assert result.created_at  # when the file was last written


def test_the_projects_saved_results_are_listed_newest_first(service, project, tmp_path):
    folder = tmp_path / "Project 1" / "analysis"
    save_result(folder, "older", "2024-06-01T09:00:00", "")
    save_result(folder, "newer", "2024-07-01T09:00:00", "")
    (folder / "analysis_results.json").write_text("{}")  # not a result
    (folder / "notes.txt").write_text("not a result")
    results = service.list_saved_results(project.analysis_dir)
    assert [r.id for r in results] == ["id-newer", "id-older"]
    assert service.list_saved_results(str(tmp_path / "missing")) == []


def test_the_facade_lists_the_open_projects_results(service, project, tmp_path):
    save_result(tmp_path / "Project 1" / "analysis", "result", "2024-07-01T10:00:00", "")
    requests = MagicMock()
    requests.get_current_project.return_value = project
    facade = BusinessFacade(user_service=MagicMock(), request_service=requests, download_service=MagicMock(),
                            map_service=MagicMock(), analysis_service=service)
    assert [r.id for r in facade.list_saved_results()] == ["id-result"]
    requests.get_current_project.return_value = None
    assert facade.list_saved_results() == []
