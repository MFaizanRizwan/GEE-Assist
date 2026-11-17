"""Drawing a report as a PDF: the analysis pictures on top, then the explanation (no window on screen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

PyQt6 = pytest.importorskip("PyQt6")
from PyQt6.QtCore import QUrl  # noqa: E402
from PyQt6.QtGui import QTextDocument  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from backend.business.explanation.previews import rgba_to_png  # noqa: E402
from backend.dto.map_dto import LegendDTO  # noqa: E402
from backend.dto.report_dto import ReportDTO, ReportImageDTO  # noqa: E402
from frontend.report_pdf import (  # noqa: E402
    blend,
    colour_key_html,
    name_blank_table_headers,
    render_report_pdf,
    report_document,
)

app = QApplication.instance() or QApplication([])

MARKDOWN = """# AI explanation: Vegetation (NDVI)

- Result: result.tif

| | |
|---|---|
| NDVI mean | 0.42 |

## Summary
The fields are **healthy**.
"""
SCALE = LegendDTO("scale", "NDVI", -0.2, 0.8, ("#A50026", "#FFFFBF", "#1A7837"))


def picture(title="NDVI", key=SCALE) -> ReportImageDTO:
    rgba = np.zeros((40, 50, 4), np.uint8)
    rgba[..., 1] = 160
    rgba[..., 3] = 255
    return ReportImageDTO(title, rgba_to_png(rgba), 50, 40, "red to green", key)


def report(**changes) -> ReportDTO:
    values = dict(title="AI explanation: Vegetation (NDVI)", explanation_path="C:/p/explanation/result_explanation.md",
                  markdown=MARKDOWN, result_path="C:/p/analysis/result.tif", images=(picture(), picture("EVI")))
    values.update(changes)
    return ReportDTO(**values)


def test_the_pictures_come_first_then_the_explanation():
    document = report_document(report())
    text = document.toPlainText()
    assert text.index("NDVI") < text.index("EVI") < text.index("AI explanation: Vegetation (NDVI)")
    assert text.index("AI explanation") < text.index("NDVI mean") < text.index("The fields are healthy.")
    for index in range(2):
        image = document.resource(QTextDocument.ResourceType.ImageResource, QUrl(f"report-image://{index}"))
        assert image is not None and not image.isNull()


def fragments(document):
    """(text, bold, heading level) of every piece of text in the document."""
    block = document.begin()
    while block.isValid():
        pieces = block.begin()
        while not pieces.atEnd():
            fragment = pieces.fragment()
            yield fragment.text(), fragment.charFormat().font().bold(), block.blockFormat().headingLevel()
            pieces += 1
        block = block.next()


def test_the_explanation_markdown_keeps_its_formatting():
    found = {text: (bold, level) for text, bold, level in fragments(report_document(report()))}
    assert found["healthy"] == (True, 0)                   # **healthy**
    assert found["Summary"][1] == 2                        # ## Summary
    assert found["AI explanation: Vegetation (NDVI)"][1] == 1
    assert "NDVI mean" in found                            # the table


def test_a_report_without_pictures_says_why():
    text = report_document(report(images=(), note="The analysis result is not in the project.")).toPlainText()
    assert text.startswith("The analysis result is not in the project.")


def test_the_pdf_is_a_titled_pdf():
    pdf = render_report_pdf(report())
    assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF")
    assert len(pdf) > 2000


def test_a_colour_scale_is_drawn_as_a_bar_with_its_range():
    key = colour_key_html(SCALE)
    assert key.count("bgcolor") == 24 and "-0.2" in key and "0.8" in key


def test_classes_are_drawn_as_swatches_with_their_names():
    key = colour_key_html(LegendDTO("classes", "Land cover", colours=("#419BDF", "#397D49"), labels=("Water", "Trees")))
    assert "Water" in key and "Trees" in key and "#419BDF" in key


def test_nothing_to_draw_gives_no_key():
    assert colour_key_html(None) == ""
    assert colour_key_html(LegendDTO("rgb", "True colour", labels=("B4", "B3", "B2"))) == ""


def test_blending_keeps_the_end_colours_and_passes_the_middle():
    colours = blend(("#000000", "#ffffff"), 3)
    assert colours == ["#000000", "#808080", "#ffffff"]
    assert blend(("#123456",), 4) == ["#123456"] * 4


# ------------------------------------------------------------------ tables
def tables(document):
    from PyQt6.QtGui import QTextTable

    return [frame for frame in document.rootFrame().childFrames() if isinstance(frame, QTextTable)]


def cell_text(table, row, column):
    cell = table.cellAt(row, column)
    cursor = cell.firstCursorPosition()
    cursor.setPosition(cell.lastCursorPosition().position(), cursor.MoveMode.KeepAnchor)
    return cursor.selectedText()


def test_a_table_saved_without_column_names_gets_them_instead_of_a_blank_row():
    document = report_document(report())  # kept alive while its table is read
    table = next(table for table in tables(document) if cell_text(table, table.rows() - 1, 0) == "NDVI mean")
    assert table.rows() == 2  # header and one row, no blank row
    assert [cell_text(table, 0, 0), cell_text(table, 0, 1)] == ["Property", "Value"]
    assert [cell_text(table, 1, 0), cell_text(table, 1, 1)] == ["NDVI mean", "0.42"]


def test_tables_with_column_names_are_left_alone():
    markdown = "| Result | Value |\n|---|---|\n| NDVI mean | 0.42 |\n"
    assert name_blank_table_headers(markdown) == markdown


def test_blank_headers_of_other_widths_are_numbered():
    assert name_blank_table_headers("| | | |\n|:--|:-:|--:|\n| a | b | c |") == \
        "| Column 1 | Column 2 | Column 3 |\n|:--|:-:|--:|\n| a | b | c |"


def test_a_blank_row_inside_a_table_is_not_a_header():
    markdown = "| Result | Value |\n|---|---|\n| | |\n| x | 1 |"
    assert name_blank_table_headers(markdown) == markdown


def test_explanation_tables_have_a_shaded_repeated_header_and_colour_keys_are_untouched():
    from frontend.report_pdf import HEADER_BACKGROUND

    document = report_document(report())
    found = tables(document)
    explanation = next(table for table in found if cell_text(table, table.rows() - 1, 0) == "NDVI mean")
    assert explanation.format().headerRowCount() == 1  # repeated at the top of a new page
    assert explanation.cellAt(0, 0).format().background().color().name().upper() == HEADER_BACKGROUND.upper()
    assert explanation.cellAt(1, 0).format().background().style().name == "NoBrush"
    keys = [table for table in found if table is not explanation]
    assert keys and all(table.format().headerRowCount() == 0 for table in keys)


def test_the_colour_bar_is_as_wide_as_its_picture_with_the_range_under_its_ends():
    key = colour_key_html(SCALE, 437)
    assert "<table width='437'" in key
    assert "align='left'" in key and "align='right'" in key  # low under the left end, high under the right
    assert key.index("-0.2") < key.index("0.8")


def test_the_colour_bar_lines_up_with_the_picture_in_the_document():
    from PyQt6.QtGui import QTextTable

    document = report_document(report(images=(picture(),)))
    image_width = None
    block = document.begin()
    while block.isValid() and image_width is None:
        pieces = block.begin()
        while not pieces.atEnd():
            form = pieces.fragment().charFormat()
            if form.isImageFormat():
                image_width = form.toImageFormat().width()
            pieces += 1
        block = block.next()
    bar = next(frame for frame in document.rootFrame().childFrames() if isinstance(frame, QTextTable))
    assert bar.format().width().rawValue() == round(image_width)
