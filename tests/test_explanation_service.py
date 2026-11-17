"""ExplanationService: the metadata before and after an analysis, the previews and the kept answer."""

from __future__ import annotations

import json
import struct
import zlib
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin  # noqa: E402

from backend.business.explanation import ExplanationService  # noqa: E402
from backend.business.explanation.explanation_service import ground_size  # noqa: E402
from backend.business.explanation.previews import describe_legend, rgba_to_png  # noqa: E402
from backend.business.map import MapService  # noqa: E402
from backend.data.dao.formula_dao import FormulaDAO  # noqa: E402
from backend.dto.download_dto import DatasetDTO  # noqa: E402
from backend.dto.explanation_dto import ExplanationDTO  # noqa: E402
from backend.dto.map_dto import LegendDTO  # noqa: E402
from backend.dto.result_dto import ResultDTO, ResultLayerDTO  # noqa: E402
from backend.exceptions import ExplanationError, MapError  # noqa: E402

DATASET_NAME = "Sentinel-2_73.0250_31.0800_2024-06-01_2024-06-30"
EARLIER_NAME = "Sentinel-2_73.0250_31.0800_2023-06-01_2023-06-30"


def write_tif(path, bands: dict, pixel=0.001):
    arrays = list(bands.values())
    height, width = arrays[0].shape
    with rasterio.open(path, "w", driver="GTiff", width=width, height=height, count=len(arrays), dtype="float32",
                       crs="EPSG:4326", transform=from_origin(73.0, 31.1, pixel, pixel), nodata=-9999.0) as dst:
        for index, (name, data) in enumerate(bands.items(), start=1):
            dst.write(data.astype("float32"), index)
            dst.set_band_description(index, name)
    return str(path)


@pytest.fixture
def project(tmp_path):
    """A project with a downloaded dataset, an earlier one and a saved NDVI result (with its .json)."""
    downloads, analysis = tmp_path / "downloads", tmp_path / "analysis"
    downloads.mkdir()
    analysis.mkdir()
    shape = (40, 50)
    dataset = write_tif(downloads / f"{DATASET_NAME}.tif", {"B4": np.full(shape, 0.1), "B8": np.full(shape, 0.5)})
    earlier = write_tif(downloads / f"{EARLIER_NAME}.tif", {"B4": np.full(shape, 0.2), "B8": np.full(shape, 0.3)})
    ndvi = np.linspace(-0.2, 0.8, shape[0] * shape[1]).reshape(shape)
    tif = write_tif(analysis / "result.tif", {"NDVI": ndvi})
    (analysis / "result.json").write_text(json.dumps({"params": {"savi_l": 0.5}, "compared_with": [earlier]}))
    result = ResultDTO("r1", "Vegetation", ["NDVI"], {"NDVI mean": 0.3}, tif, "2024-07-01T10:00:00",
                       DatasetDTO("d1", "S2", dataset, name=DATASET_NAME, satellite="Sentinel-2"),
                       [ResultLayerDTO("NDVI", "NDVI", "vegetation", "", -0.2, 0.8)], device="CPU", seconds=1.5,
                       saved=True)
    return result


@pytest.fixture
def data_facade():
    facade = MagicMock()
    dao = FormulaDAO()
    facade.get_formula.side_effect = dao.find_by_key
    facade.analysis_groups.return_value = [("Vegetation", "Vegetation health", "", ())]
    facade.generate_explanation.side_effect = lambda request: ExplanationDTO("## Summary\nGreen.", "gemini-test")
    return facade


@pytest.fixture
def service(data_facade):
    return ExplanationService(data_facade, MapService(), preview_size=64, now=lambda: datetime(2024, 7, 2, 9, 30))


def test_the_request_names_the_analysis_its_processes_and_settings(service, project):
    request = service.prepare(project)
    assert request.result is project and request.tif_path == project.output_path
    assert (request.category, request.category_label) == ("Vegetation", "Vegetation health")
    ndvi = request.processes[0]
    assert ndvi.key == "NDVI" and ndvi.name == "Normalized Difference Vegetation Index" and ndvi.formula
    assert request.params == {"savi_l": 0.5}


def test_the_metadata_before_and_after_the_analysis_is_read_from_the_files(service, project):
    request = service.prepare(project)
    before, after = request.before, request.after
    assert before.name == DATASET_NAME and before.satellite == "Sentinel-2"
    assert (before.start_date, before.end_date) == ("2024-06-01", "2024-06-30")
    assert before.bands == ("B4", "B8") and (before.width, before.height) == (50, 40)
    assert before.crs == "EPSG:4326" and before.bounds == pytest.approx((73.0, 31.06, 73.05, 31.1))
    assert before.pixel_size_m == pytest.approx(103, abs=3) and before.area_km2 == pytest.approx(21.1, abs=0.5)
    assert [other.start_date for other in request.compared_with] == ["2023-06-01"]
    assert after.name == "result" and after.bands == ("NDVI",) and after.nodata == -9999.0


def test_each_layer_gets_a_png_preview_and_its_colours(service, project):
    request = service.prepare(project)
    assert [layer.key for layer in request.layers] == ["NDVI"]
    assert "over -0.2 to 0.8" in request.layers[0].legend
    png = request.previews[0]
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (50, 40)


def test_only_a_saved_result_can_be_explained(service, project):
    with pytest.raises(ExplanationError, match="Save the result"):
        service.prepare(replace(project, saved=False))
    with pytest.raises(ExplanationError, match="no longer there"):
        service.prepare(replace(project, output_path=project.output_path + ".gone"))


def test_unreadable_datasets_fall_back_to_what_is_known(data_facade, project):
    maps = MagicMock(wraps=MapService())
    maps.describe.side_effect = MapError("unreadable")
    maps.build_layers.side_effect = MapError("unreadable")
    request = ExplanationService(data_facade, maps).prepare(project)
    assert request.before.name == DATASET_NAME and request.before.satellite == "Sentinel-2"
    assert request.before.width == 0 and request.previews == ()
    assert request.layers[0].legend == ""


def test_the_explanation_is_kept_next_to_the_result(service, project, data_facade):
    request = service.prepare(project)
    explanation = service.explain(request)

    data_facade.generate_explanation.assert_called_once_with(request)
    assert explanation.request is request and explanation.created_at == "2024-07-02T09:30:00"
    saved = explanation.saved_path
    assert saved.endswith("result_explanation.md")
    text = open(saved, encoding="utf-8").read()
    assert text.startswith("# AI explanation: Vegetation health (NDVI)")
    assert "## Before the analysis: dataset" in text and "## After the analysis: result" in text
    assert "| NDVI mean | 0.3 |" in text and text.rstrip().endswith("Green.")


def test_a_deleted_geotiff_is_not_sent(service, project, data_facade):
    request = service.prepare(project)
    Path(project.output_path).unlink()
    with pytest.raises(ExplanationError):
        service.explain(request)
    data_facade.generate_explanation.assert_not_called()


def test_png_encoding_round_trips():
    rgba = np.zeros((3, 2, 4), np.uint8)
    rgba[1, 1] = (10, 20, 30, 255)
    png = rgba_to_png(rgba)
    idat = png[png.index(b"IDAT") + 4:png.index(b"IEND") - 8]
    rows = np.frombuffer(zlib.decompress(idat), np.uint8).reshape(3, 1 + 2 * 4)
    assert (rows[:, 0] == 0).all() and tuple(rows[1, 5:9]) == (10, 20, 30, 255)


def test_legends_are_described_in_words():
    assert describe_legend(LegendDTO("scale", "NDVI", -0.2, 0.8, ("#a50026", "#006837"))) == \
        "from #a50026 (low) to #006837 (high) over -0.2 to 0.8; transparent = no data"
    assert describe_legend(LegendDTO("classes", "Land", colours=("#419bdf",), labels=("Water",))) == \
        "classes: Water = #419bdf"
    assert describe_legend(None) == ""


def test_ground_size_needs_a_real_area():
    assert ground_size((0, 0, 0, 0), 10, 10) == (None, None)
    assert ground_size(None, 10, 10) == (None, None)
