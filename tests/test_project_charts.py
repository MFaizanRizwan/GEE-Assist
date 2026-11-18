"""The dashboard's charts of a project's analyses (no window on screen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

PyQt6 = pytest.importorskip("PyQt6")
from PyQt6.QtGui import QColor  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from frontend.widgets.project_charts import CategoryBarChart  # noqa: E402

app = QApplication.instance() or QApplication([])


def _drawn(widget):
    """True when the widget painted something other than its background."""
    image = widget.grab().toImage()
    background = QColor(image.pixel(0, 0))
    return any(QColor(image.pixel(x, y)) != background
               for x in range(0, image.width(), 4) for y in range(0, image.height(), 2))


def test_bars_are_as_long_as_their_counts():
    chart = CategoryBarChart()
    chart.set_counts([("Vegetation", 4), ("Water", 2), ("Land cover", 1)])
    chart.resize(600, chart.height())
    widths = [bar.width() for bar in chart.bar_rects()]
    assert widths[0] > widths[1] > widths[2] > 0
    assert widths[0] == pytest.approx(2 * widths[1]) and widths[1] == pytest.approx(2 * widths[2])
    lefts = {bar.left() for bar in chart.bar_rects()}
    assert len(lefts) == 1  # every bar starts at the same place, after the left-aligned names


def test_the_chart_is_as_tall_as_its_bars_and_says_what_it_shows():
    chart = CategoryBarChart()
    chart.set_counts([("Vegetation", 4), ("Water", 2)])
    two = chart.height()
    chart.set_counts([("Vegetation", 4), ("Water", 2), ("LST", 1)])
    assert chart.height() > two
    assert chart.toolTip() == "Vegetation: 4\nWater: 2\nLST: 1"
    assert chart.accessibleDescription() == "7 analyses: 4 Vegetation, 2 Water, 1 LST"


def test_types_without_analyses_are_left_out_and_an_empty_chart_says_so():
    chart = CategoryBarChart()
    chart.set_counts([("Vegetation", 0)])
    assert chart.counts == [] and chart.bar_rects() == [] and chart.toolTip() == "No analyses yet"


def test_the_chart_draws_in_every_state():
    chart = CategoryBarChart()
    chart.resize(500, 100)
    for counts in ([], [("Vegetation", 3), ("Water", 1)]):
        chart.set_counts(counts)
        assert _drawn(chart)
