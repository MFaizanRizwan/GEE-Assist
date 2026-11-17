"""Draw a report (``ReportDTO``) as an A4 PDF with Qt: the analysis pictures on top, each
with its colour key (a colour bar with its range, or the classes), then the AI explanation
(its Markdown: headings, tables, lists, emphasis) below them."""

from __future__ import annotations

import html

from PyQt6.QtCore import QBuffer, QIODevice, QMarginsF, Qt, QUrl
from PyQt6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPageLayout,
    QPageSize,
    QPdfWriter,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFrameFormat,
    QTextImageFormat,
    QTextLength,
    QTextTable,
)

from backend.dto.map_dto import LegendDTO
from backend.dto.report_dto import ReportDTO
from frontend.widgets.raster_legend import format_value

PAGE_MARGIN_MM = 18
RESOLUTION_DPI = 300
IMAGE_WIDTH = 620                               # in document pixels: about the text width of an A4 page
MUTED = "#5f6b6d"
IMAGE_URL = "report-image://{}"
BAR_CELLS = 24                                  # colours blended across a colour bar
BAR_CELL_WIDTH = 12
SECTION_GAP = 14                                # space between pictures, and before the explanation
BLANK_HEADER_NAMES = ("Property", "Value")      # for two-column tables saved without column names
HEADER_BACKGROUND = "#E6EFEC"                   # the explanation tables' header row
TABLE_BORDER = "#B9C4C1"


def report_document(report: ReportDTO) -> QTextDocument:
    """The report laid out as a document: each analysis picture with its title and colours,
    then the explanation exactly as saved."""
    document = QTextDocument()
    document.setDocumentMargin(0)
    document.setDefaultFont(QFont("Segoe UI", 10))
    document.setMetaInformation(QTextDocument.MetaInformation.DocumentTitle, report.title)
    cursor = QTextCursor(document)

    centred = QTextBlockFormat()
    centred.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    for index, image in enumerate(report.images):
        picture = QImage.fromData(image.png, "PNG")
        if picture.isNull():
            continue
        url = QUrl(IMAGE_URL.format(index))
        document.addResource(QTextDocument.ResourceType.ImageResource, url, picture)
        title = QTextBlockFormat(centred)
        title.setTopMargin(SECTION_GAP if index else 0)
        if index:
            cursor.insertBlock()
        cursor.setBlockFormat(title)
        cursor.insertText(image.title, _char(bold=True, size=11))
        cursor.insertBlock(centred)
        width = min(IMAGE_WIDTH, max(IMAGE_WIDTH // 2, picture.width()))  # small results are enlarged
        picture_format = QTextImageFormat()
        picture_format.setName(url.toString())
        picture_format.setWidth(width)
        picture_format.setHeight(width * picture.height() / max(1, picture.width()))
        cursor.insertImage(picture_format)
        key = colour_key_html(image.colour_key)
        if key:
            cursor.insertBlock(centred)
            cursor.insertHtml(key)
        elif image.legend:
            cursor.insertBlock(centred)
            cursor.insertText(f"Colours: {image.legend}", _char(size=8.5, colour=MUTED))
    if report.note:
        if report.images:
            cursor.insertBlock()
        cursor.setBlockFormat(QTextBlockFormat())
        cursor.insertText(report.note, _char(italic=True, colour=MUTED))

    above = bool(report.images or report.note)
    if above:
        cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
    start = cursor.position()
    markdown = name_blank_table_headers(report.markdown)
    cursor.insertMarkdown(markdown)
    # The explanation's first block is merged into the empty block it was inserted in and takes
    # that block's format: give it back its own (e.g. its heading level), with a gap above it.
    source = QTextDocument()
    source.setMarkdown(markdown)
    first = QTextBlockFormat(source.begin().blockFormat())
    first.setTopMargin(max(first.topMargin(), SECTION_GAP if above else 0))
    QTextCursor(document.findBlock(start)).setBlockFormat(first)
    style_explanation_tables(document, start)
    return document


def style_explanation_tables(document: QTextDocument, start: int = 0) -> None:
    """The explanation's tables (those from ``start`` on, not the colour keys above it) across the
    page, with a shaded header row that is repeated when a table runs onto the next page."""
    for frame in document.rootFrame().childFrames():
        if not isinstance(frame, QTextTable) or frame.firstPosition() < start:
            continue
        table_format = frame.format()
        table_format.setHeaderRowCount(1)
        table_format.setWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
        table_format.setCellPadding(4)
        table_format.setCellSpacing(0)
        table_format.setBorder(1)
        table_format.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
        table_format.setBorderCollapse(True)
        table_format.setBorderBrush(QColor(TABLE_BORDER))
        frame.setFormat(table_format)
        for column in range(frame.columns()):
            cell = frame.cellAt(0, column)
            cell_format = cell.format().toTableCellFormat()
            cell_format.setBackground(QColor(HEADER_BACKGROUND))
            cell.setFormat(cell_format)


def name_blank_table_headers(markdown: str) -> str:
    """Give column names to tables whose header row is empty (``| | |``), as explanations saved
    before their tables had headers were written: otherwise they show a blank first row."""
    lines = markdown.split("\n")
    for index, line in enumerate(lines[:-1]):
        cells = _table_cells(line)
        if cells is None or any(cells) or not _is_separator(lines[index + 1]):
            continue
        names = list(BLANK_HEADER_NAMES) if len(cells) == len(BLANK_HEADER_NAMES) else \
            [f"Column {number}" for number in range(1, len(cells) + 1)]
        lines[index] = "| " + " | ".join(names) + " |"
    return "\n".join(lines)


def _table_cells(line: str) -> list[str] | None:
    """The cells of a Markdown table row, stripped; None if ``line`` is not one."""
    text = line.strip()
    if len(text) < 2 or not (text.startswith("|") and text.endswith("|")):
        return None
    return [cell.strip() for cell in text[1:-1].split("|")]


def _is_separator(line: str) -> bool:
    """A table's header separator, e.g. ``|---|:---:|``."""
    cells = _table_cells(line)
    return bool(cells) and all(cell and set(cell) <= set("-:") and "-" in cell for cell in cells)


def render_report_pdf(report: ReportDTO) -> bytes:
    """The report as the bytes of an A4 PDF."""
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QPdfWriter(buffer)
    writer.setTitle(report.title)
    writer.setCreator("GEE-Assist")
    writer.setResolution(RESOLUTION_DPI)
    writer.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                                     QMarginsF(*[PAGE_MARGIN_MM] * 4), QPageLayout.Unit.Millimeter))
    report_document(report).print(writer)
    del writer  # finishes the PDF
    buffer.close()
    return bytes(buffer.data())


def colour_key_html(legend: LegendDTO | None) -> str:
    """A colour bar with its low and high values, or a swatch per class; "" if there is nothing to draw."""
    if legend is None or not legend.colours:
        return ""
    if legend.kind == "scale":
        cells = "".join(f"<td width='{BAR_CELL_WIDTH}' bgcolor='{colour}'>&nbsp;</td>"
                        for colour in blend(legend.colours, BAR_CELLS))
        return (f"<table cellspacing='0' cellpadding='1' align='center'><tr>"
                f"<td style='color:{MUTED}; font-size:8pt'>{html.escape(format_value(legend.low))}&nbsp;</td>"
                f"{cells}<td style='color:{MUTED}; font-size:8pt'>&nbsp;{html.escape(format_value(legend.high))}</td>"
                f"</tr></table>")
    if legend.kind == "classes" and legend.labels:
        cells = "".join(f"<td width='12' bgcolor='{colour}'>&nbsp;</td>"
                        f"<td style='font-size:8pt'>&nbsp;{html.escape(label)}&nbsp;&nbsp;&nbsp;</td>"
                        for label, colour in zip(legend.labels, legend.colours))
        return f"<table cellspacing='0' cellpadding='1' align='center'><tr>{cells}</tr></table>"
    return ""


def blend(colours: tuple[str, ...], count: int) -> list[str]:
    """``count`` colours spread evenly along the stops ``colours`` ("#RRGGBB"), ends included."""
    stops = [QColor(colour) for colour in colours]
    if len(stops) == 1 or count < 2:
        return [stops[0].name()] * max(1, count)
    blended = []
    for index in range(count):
        position = index / (count - 1) * (len(stops) - 1)
        left = min(int(position), len(stops) - 2)
        t = position - left
        a, b = stops[left], stops[left + 1]
        blended.append(QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                              round(a.blue() + (b.blue() - a.blue()) * t)).name())
    return blended


def _char(bold: bool = False, italic: bool = False, size: float = 0, colour: str = "") -> QTextCharFormat:
    form = QTextCharFormat()
    if bold:
        form.setFontWeight(QFont.Weight.Bold)
    form.setFontItalic(italic)
    if size:
        form.setFontPointSize(size)
    if colour:
        form.setForeground(QColor(colour))
    return form
