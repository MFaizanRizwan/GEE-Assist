"""Writing a report as a PDF with markdown-pdf, checked on the PDF itself with PyMuPDF."""

from __future__ import annotations

import numpy as np
import pytest

pymupdf = pytest.importorskip("pymupdf")
pytest.importorskip("markdown_pdf")

from backend.business.explanation.previews import rgba_to_png  # noqa: E402
from backend.business.report.pdf_writer import (  # noqa: E402
    MARGIN_PT,
    WORD_BREAK,
    breakable_long_words,
    colour_bar_png,
    format_number,
    keep_tables_together,
    name_blank_table_headers,
    picture_size,
    write_report_pdf,
)
from backend.dto.map_dto import LegendDTO  # noqa: E402
from backend.dto.report_dto import ReportDTO, ReportImageDTO  # noqa: E402

RESULT = "Sentinel-2_73.0708_31.4357_2026-08-14_2026-11-14_Vegetation_NDVI_EVI_2026-11-14_23-02-58.tif"
MARKDOWN = f"""# Summary: Vegetation (NDVI)

- Result: {RESULT}

## Before the analysis: dataset

| | |
|---|---|
| File | Sentinel-2_73.0708_31.4357_2026-08-14_2026-11-14.tif |
| Satellite | Sentinel-2 |

## Summary
The fields are **healthy**.
"""
SCALE = LegendDTO("scale", "NDVI", -0.2, 0.8, ("#A50026", "#FFFFBF", "#1A7837"))


def picture(width=376, height=250, key=SCALE, title="NDVI") -> ReportImageDTO:
    rgba = np.full((height, width, 4), 180, np.uint8)
    rgba[..., 3] = 255
    return ReportImageDTO(title, rgba_to_png(rgba), width, height, "", key)


def report(**changes) -> ReportDTO:
    values = dict(title="Summary: Vegetation (NDVI)", explanation_path="C:/p/explanation/x_explanation.md",
                  markdown=MARKDOWN, images=(picture(),))
    values.update(changes)
    return ReportDTO(**values)


def pdf_of(**changes):
    return pymupdf.open(stream=write_report_pdf(report(**changes)), filetype="pdf")


def text_of(page) -> str:
    """The page's text with ligatures (e.g. the "fi" in "fields") written out."""
    return page.get_text(flags=0)


# ------------------------------------------------------------------ the PDF
def test_the_pdf_is_titled_numbered_and_bookmarked():
    document = pdf_of()
    assert document.metadata["title"] == "Summary: Vegetation (NDVI)"
    assert document.metadata["creator"] == "GEE-Assist"
    count = document.page_count
    for number, page in enumerate(document, start=1):
        assert f"Page {number} of {count}" in page.get_text()
    assert [entry[1] for entry in document.get_toc()][:2] == ["Summary: Vegetation (NDVI)",
                                                               "Before the analysis: dataset"]


def test_the_picture_comes_first_then_the_explanation():
    page = pdf_of()[0]
    picture_box = pymupdf.Rect(page.get_image_info()[0]["bbox"])
    heading = page.search_for("Summary: Vegetation (NDVI)")[0]
    assert picture_box.y1 < heading.y0
    assert "The fields are healthy." in " ".join(text_of(p) for p in pdf_of()).replace("\n", " ")


@pytest.mark.parametrize(("width", "height"), [(50, 40), (333, 200), (376, 250), (1400, 900), (300, 1200)])
def test_the_colour_bar_lines_up_with_its_picture_and_both_are_centred(width, height):
    page = pdf_of(images=(picture(width, height),))[0]
    shown, bar = (pymupdf.Rect(info["bbox"]) for info in page.get_image_info())
    assert (bar.x0, bar.x1) == pytest.approx((shown.x0, shown.x1), abs=0.01)   # same left and right edges
    assert (shown.x0 + shown.x1) / 2 == pytest.approx(page.rect.width / 2, abs=0.5)  # centred on the page
    assert bar.y0 >= shown.y1  # under the picture
    low, high = page.search_for("-0.2")[0], page.search_for("0.8")[0]
    assert low.x0 == pytest.approx(bar.x0, abs=0.5) and high.x1 == pytest.approx(bar.x1, abs=0.5)


def test_land_cover_classes_get_swatches_and_names():
    classes = LegendDTO("classes", "Land cover", colours=("#419BDF", "#397D49"), labels=("Water", "Trees"))
    page = pdf_of(images=(picture(key=classes, title="Land cover"),))[0]
    text = page.get_text()
    assert "Water" in text and "Trees" in text and len(page.get_image_info()) == 1  # no colour bar image


def test_a_report_without_pictures_says_why():
    page = pdf_of(images=(), note="The analysis result x.tif is not in the project's analysis folder.")[0]
    assert page.get_image_info() == []
    assert page.get_text().startswith("The analysis result x.tif is not in the project")


def test_a_header_less_table_gets_column_names_and_no_blank_row():
    page = pdf_of()[0]
    words = [word[4] for word in page.get_text("words")]
    property_at = words.index("Property")
    assert words[property_at + 1:property_at + 3] == ["Value", "File"]


def test_long_file_names_wrap_inside_the_page():
    document = pdf_of(images=())
    right_edge = document[0].rect.width - MARGIN_PT
    for page in document:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                assert line["bbox"][2] <= right_edge + 1, line["spans"][0]["text"]
    text = text_of(document[0])
    assert "2026-11-14_" in text and "23-02-58.tif" in text  # dates are not broken at their "-"
    file_cell = document[0].search_for("Sentinel-2_73.0708_31.4357_2026-08-14_2026-11-14.tif")
    assert len(file_cell) == 1  # the table cell keeps the whole name on one line


def test_a_heading_and_its_table_are_never_split_across_pages():
    # two tall pictures push the "Before the analysis" heading and table to the foot of page 1
    document = pdf_of(images=(picture(1400, 900), picture(1400, 900, title="EVI")))
    def page_of(text):
        return next(page.number for page in document if page.search_for(text))
    assert page_of("Before the analysis") == page_of("Satellite") == page_of("Property")


# ------------------------------------------------------------------ parts
def test_blank_headers_are_named_and_real_ones_kept():
    assert name_blank_table_headers("| | |\n|---|---|\n| a | 1 |") == "| Property | Value |\n|---|---|\n| a | 1 |"
    assert name_blank_table_headers("| | | |\n|:--|:-:|--:|") == "| Column 1 | Column 2 | Column 3 |\n|:--|:-:|--:|"
    kept = "| Result | Value |\n|---|---|\n| | |"
    assert name_blank_table_headers(kept) == kept


def test_only_long_words_get_break_points_and_links_and_code_are_kept():
    assert breakable_long_words("short_word stays") == "short_word stays"
    softened = breakable_long_words(f"Result: {RESULT}")
    assert softened.count(WORD_BREAK) == RESULT.count("_")
    row = f"| File | {RESULT} |"
    assert breakable_long_words(row) == row  # tables are left alone
    link = "https://example.com/a_very_long_path_name_that_goes_on_and_on_and_on"
    assert breakable_long_words(link) == link
    code = f"```\n{RESULT}\n```"
    assert breakable_long_words(code) == code


def test_tables_are_wrapped_with_the_heading_above_them():
    wrapped = keep_tables_together("## Numbers\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nAfter.")
    assert wrapped.startswith('<table class="keep"') and "## Numbers\n\n| a | b |" in wrapped
    assert wrapped.rstrip().endswith("After.")


def test_picture_sizes():
    assert picture_size(50, 40) == (235, 188)            # small results are enlarged
    assert picture_size(1400, 700) == (470, 235)         # wide ones fill the column
    width, height = picture_size(300, 1200)
    assert height == 470 and width == pytest.approx(117.5)  # tall ones are narrowed to fit


def test_the_colour_bar_runs_from_the_first_colour_to_the_last():
    page = pymupdf.Pixmap(colour_bar_png(("#000000", "#FFFFFF")))
    assert page.pixel(0, 0)[:3] == (0, 0, 0) and page.pixel(page.width - 1, 0)[:3] == (255, 255, 255)


def test_numbers_read_briefly():
    assert [format_number(v) for v in (-0.2, 0.8, 1530.0, 2.0, 1.234, 0.00004)] == \
        ["-0.2", "0.8", "1,530", "2", "1.23", "4e-05"]
