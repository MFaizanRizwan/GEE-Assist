"""ReportService: reports made from saved AI explanations, kept in the project and exported."""

from __future__ import annotations

import json
import struct
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin  # noqa: E402

from backend.business.map import MapService  # noqa: E402
from backend.business.report import ReportService  # noqa: E402
from backend.dto.project_dto import ProjectDTO  # noqa: E402
from backend.dto.result_dto import ResultLayerDTO  # noqa: E402
from backend.exceptions import MapError, ReportError  # noqa: E402

RESULT = "Sentinel-2_73.0250_31.0800_2024-06-01_2024-06-30_Vegetation_NDVI_2024-07-01_10-00-00"
EXPLANATION = f"""# AI explanation: Vegetation (NDVI)

- Result: {RESULT}.tif
- Explained: 2024-07-02T09:30:00 by gemini-test

## Numbers

| | |
|---|---|
| NDVI mean | 0.3 |

---

## Summary
The fields are healthy.
"""


def write_result(path, layers=(ResultLayerDTO("NDVI", "NDVI", "vegetation", "", -0.2, 0.8),)):
    shape = (40, 50)
    with rasterio.open(path, "w", driver="GTiff", width=shape[1], height=shape[0], count=len(layers),
                       dtype="float32", crs="EPSG:4326", transform=from_origin(73.0, 31.1, 0.001, 0.001),
                       nodata=-9999.0) as dst:
        for index, layer in enumerate(layers, start=1):
            dst.write(np.linspace(-0.2, 0.8, shape[0] * shape[1]).reshape(shape).astype("float32"), index)
            dst.set_band_description(index, layer.key)
    summary = {"category": "Vegetation", "layers": [layer.key for layer in layers],  # as an analysis writes it
               "styles": [asdict(layer) for layer in layers]}
    path.with_suffix(".json").write_text(json.dumps(summary))


@pytest.fixture
def project(tmp_path):
    project = ProjectDTO("p1", "Project 1", str(tmp_path / "Project 1"))
    for folder in ("analysis", "explanation", "reports"):
        (tmp_path / "Project 1" / folder).mkdir(parents=True)
    write_result(tmp_path / "Project 1" / "analysis" / f"{RESULT}.tif")
    (tmp_path / "Project 1" / "explanation" / f"{RESULT}_explanation.md").write_text(EXPLANATION, encoding="utf-8")
    return project


@pytest.fixture
def service():
    return ReportService(MapService(), image_size=200, now=lambda: datetime(2024, 7, 3, 8, 0))


def explanation_path(project: ProjectDTO, name: str = f"{RESULT}_explanation.md") -> str:
    return str(Path(project.explanation_dir) / name)


def test_the_report_has_the_analysis_picture_then_the_explanation(service, project):
    report = service.build_report(explanation_path(project), project)
    assert report.title == "Summary: Vegetation (NDVI)"
    assert report.markdown == EXPLANATION.replace("# AI explanation:", "# Summary:", 1)  # otherwise as saved
    assert Path(report.result_path) == Path(project.analysis_dir) / f"{RESULT}.tif"
    image = report.images[0]
    assert image.png.startswith(b"\x89PNG") and struct.unpack(">II", image.png[16:24]) == (50, 40)
    assert (image.width, image.height) == (50, 40)
    assert "over -0.2 to 0.8" in image.legend and image.title == "NDVI"
    assert image.colour_key.kind == "scale" and (image.colour_key.low, image.colour_key.high) == (-0.2, 0.8)
    assert report.note == "" and report.created_at == "2024-07-03T08:00:00"


def test_a_plain_geotiff_gets_its_default_view(project, tmp_path):
    maps = MagicMock(wraps=MapService())
    report = ReportService(maps, image_size=64).build_report(explanation_path(project), project)
    assert len(report.images) == 1
    # without the .json the GeoTIFF is shown with its first view
    (tmp_path / "Project 1" / "analysis" / f"{RESULT}.json").unlink()
    report = ReportService(MapService(), image_size=64).build_report(explanation_path(project), project)
    assert len(report.images) == 1 and report.images[0].png.startswith(b"\x89PNG")


def test_a_missing_result_gives_a_report_without_a_picture(service, project, tmp_path):
    (tmp_path / "Project 1" / "analysis" / f"{RESULT}.tif").unlink()
    report = service.build_report(explanation_path(project), project)
    assert report.images == () and report.result_path == ""
    assert "is not in the project's analysis folder" in report.note
    assert report.markdown.endswith(EXPLANATION.split("\n", 1)[1])  # the explanation is still all there


def test_an_unreadable_result_is_explained_in_the_note(project):
    maps = MagicMock()
    maps.describe.side_effect = MapError("Cannot open it.")
    report = ReportService(maps).build_report(explanation_path(project), project)
    assert report.images == () and "could not be drawn: Cannot open it." in report.note


def test_an_explanation_without_a_result_line_is_matched_by_its_name(service, project, tmp_path):
    name = f"{RESULT}_explanation_2.md"
    (tmp_path / "Project 1" / "explanation" / name).write_text("# Older explanation\n\nText.", encoding="utf-8")
    report = service.build_report(explanation_path(project, name), project)
    assert report.title == "Older explanation" and len(report.images) == 1


def test_a_missing_explanation_is_reported(service, project):
    with pytest.raises(ReportError, match="cannot be read"):
        service.build_report(explanation_path(project, "gone_explanation.md"), project)


def test_explanations_are_listed_newest_first_with_their_reports(service, project, tmp_path):
    folder = tmp_path / "Project 1" / "explanation"
    (folder / "older_explanation.md").write_text("# Older\n\n- Result: older.tif\n- Explained: 2024-01-01T00:00:00\n",
                                                 encoding="utf-8")
    (tmp_path / "Project 1" / "reports" / "older_explanation.pdf").write_bytes(b"%PDF-1.4")
    listed = service.list_explanations(project)
    assert [item.title for item in listed] == ["AI explanation: Vegetation (NDVI)", "Older"]
    assert listed[0].result_name == f"{RESULT}.tif" and listed[0].explained_at == "2024-07-02T09:30:00"
    assert listed[0].report_path == "" and listed[1].report_path.endswith("older_explanation.pdf")
    assert listed[0].name == f"{RESULT}_explanation.md"


def test_no_explanation_folder_lists_nothing(service, tmp_path):
    assert service.list_explanations(ProjectDTO("p2", "Empty", str(tmp_path / "Empty"))) == []


def writing(*pdfs: bytes) -> ReportService:
    """A service whose PDF writer gives ``pdfs`` one after the other (no markdown-pdf needed)."""
    queue = list(pdfs)
    return ReportService(MapService(), image_size=64, write_pdf=lambda report: queue.pop(0))


def test_the_pdf_is_kept_in_the_reports_folder_and_replaced_when_made_again(project, tmp_path):
    service = writing(b"%PDF-1.4 first", b"%PDF-1.4 second")
    saved = service.create_report(explanation_path(project), project)
    assert saved == str(tmp_path / "Project 1" / "reports" / f"{RESULT}_explanation.pdf")
    assert service.create_report(explanation_path(project), project) == saved
    assert open(saved, "rb").read() == b"%PDF-1.4 second"
    assert service.list_explanations(project)[0].report_path == saved
    assert not list((tmp_path / "Project 1" / "reports").glob("*.tmp"))  # nothing half-written left


def test_a_report_can_be_exported_anywhere(project, tmp_path):
    service = writing(b"%PDF-1.4 report")
    saved = service.create_report(explanation_path(project), project)
    exported = service.export_report(saved, str(tmp_path / "usb" / "My report"))
    assert exported == str(tmp_path / "usb" / "My report.pdf")
    assert open(exported, "rb").read() == b"%PDF-1.4 report"
    assert open(saved, "rb").read() == b"%PDF-1.4 report"  # the project keeps its copy


def test_exporting_a_missing_report_is_refused(service, tmp_path):
    with pytest.raises(ReportError, match="no longer there"):
        service.export_report(str(tmp_path / "gone.pdf"), str(tmp_path / "out.pdf"))


def test_the_report_heading_says_summary_and_the_saved_explanation_is_unchanged(service, project):
    report = service.build_report(explanation_path(project), project)
    assert report.markdown.startswith("# Summary: Vegetation (NDVI)\n")
    assert report.markdown.count("# AI explanation") == 0
    saved = Path(explanation_path(project)).read_text(encoding="utf-8")
    assert saved == EXPLANATION  # the .md in the project keeps its own heading
    assert service.list_explanations(project)[0].title == "AI explanation: Vegetation (NDVI)"


def test_only_the_explanation_heading_is_reworded():
    from backend.business.report.report_service import report_heading

    assert report_heading("# AI explanation: Water (NDWI)\n\n## Summary\nWet.") == \
        "# Summary: Water (NDWI)\n\n## Summary\nWet."
    assert report_heading("# Older explanation\n\nText.") == "# Older explanation\n\nText."
    assert report_heading("Intro\n# AI explanation: LST\n# AI explanation: again") == \
        "Intro\n# Summary: LST\n# AI explanation: again"  # the first one only


def test_create_report_writes_the_pdf_into_the_reports_folder(project, tmp_path):
    written = []
    service = ReportService(MapService(), image_size=64,
                            write_pdf=lambda report: written.append(report) or b"%PDF-1.7 drawn")
    path = service.create_report(explanation_path(project), project)
    assert path == str(tmp_path / "Project 1" / "reports" / f"{RESULT}_explanation.pdf")
    assert Path(path).read_bytes() == b"%PDF-1.7 drawn"
    assert written[0].title == "Summary: Vegetation (NDVI)" and len(written[0].images) == 1


def test_create_report_with_markdown_pdf_gives_a_real_pdf(project):
    pymupdf = pytest.importorskip("pymupdf")
    pytest.importorskip("markdown_pdf")
    path = ReportService(MapService(), image_size=64).create_report(explanation_path(project), project)
    document = pymupdf.open(path)
    assert document.page_count >= 1 and document.metadata["title"] == "Summary: Vegetation (NDVI)"
    assert len(document[0].get_image_info()) == 2  # the NDVI picture and its colour bar


def test_a_pdf_that_cannot_be_written_is_reported(project):
    from backend.exceptions import ReportError as Error

    def fail(report):
        raise Error("The PDF could not be written: broken")
    with pytest.raises(Error, match="could not be written"):
        ReportService(MapService(), write_pdf=fail).create_report(explanation_path(project), project)
