"""Write a report (``ReportDTO``) as an A4 PDF with markdown-pdf.

The report is one Markdown document: first a figure per analysis picture (its title, the
picture, a colour bar exactly as wide as the picture and its range under the bar's ends, or
a swatch per class), then the AI explanation. markdown-pdf lays it out with PyMuPDF's HTML
engine; the figures are placed with explicit widths and margins, as that engine does not
centre blocks by itself. "Page n of N" is then written at the foot of every page.
"""

from __future__ import annotations

import html
import io
import re
import tempfile
from pathlib import Path

import numpy as np

from backend.business.explanation.previews import rgba_to_png
from backend.dto.map_dto import LegendDTO
from backend.dto.report_dto import ReportDTO, ReportImageDTO
from backend.exceptions import ReportError

PAPER = "A4"
PAGE_WIDTH_PT = 595.28                          # A4, in points (1/72 inch)
MARGIN_PT = 51                                  # 18 mm on every side
FOOTER_PT = 18                                  # extra room at the foot for "Page n of N"
TEXT_WIDTH_PT = PAGE_WIDTH_PT - 2 * MARGIN_PT
MAX_PICTURE_PT = 470                            # the widest a picture is shown
MIN_PICTURE_PT = 235                            # small results are enlarged to this
MAX_PICTURE_HEIGHT_PT = 470                     # tall pictures are narrowed to fit a page with the text
BAR_HEIGHT_PT = 9
BAR_PIXELS = 512                                # resolution of the colour bar image
MUTED = "#5f6b6d"
BLANK_HEADER_NAMES = ("Property", "Value")      # for two-column tables saved without column names

STYLESHEET = f"""
body {{ margin: 0; font-family: sans-serif; font-size: 10pt; line-height: 1.35; color: #1d2b2e; }}
h1 {{ font-size: 18pt; margin: 14pt 0 6pt 0; }}
h2 {{ font-size: 13pt; margin: 12pt 0 4pt 0; }}
h3 {{ font-size: 11pt; margin: 10pt 0 4pt 0; }}
table {{ border-collapse: collapse; width: 100%; margin: 4pt 0 8pt 0; }}
th, td {{ border: 1px solid #b9c4c1; padding: 3pt 5pt; text-align: left; vertical-align: top; }}
th {{ font-weight: bold; border-bottom: 2px solid #8fa39e; }}
code {{ font-family: monospace; }}
.figure {{ margin-top: 0; margin-bottom: 10pt; }}
.figure-title {{ font-weight: bold; font-size: 11pt; text-align: center; margin: 0 0 3pt 0; }}
.figure img {{ display: block; }}
.figure table, .figure td {{ border: none; padding: 0; margin: 0; background-color: transparent; }}
.range td {{ font-size: 8pt; color: {MUTED}; padding-top: 1pt; }}
.range .low {{ text-align: left; }}
.range .high {{ text-align: right; }}
.classes td {{ font-size: 8pt; padding: 2pt 6pt 0 0; }}
.swatch {{ width: 9pt; }}
.note {{ font-style: italic; color: {MUTED}; }}
"""


def write_report_pdf(report: ReportDTO) -> bytes:
    """The report as the bytes of an A4 PDF.

    Raises:
        ReportError: the PDF could not be written.
    """
    try:
        from markdown_pdf import MarkdownPdf, Section
        import pymupdf
    except ImportError as exc:
        raise ReportError("PDF reports need markdown-pdf. Run: pip install -r requirements.txt") from exc

    with tempfile.TemporaryDirectory(prefix="gee-assist-report-") as folder:
        text = report_markdown(report, Path(folder))
        pdf = MarkdownPdf(toc_level=2)
        now = pymupdf.get_pdf_now()
        pdf.meta = {**MarkdownPdf.meta, "title": report.title, "creator": "GEE-Assist",
                    "producer": "markdown-pdf", "creationDate": now, "modDate": now}
        section = Section(text, toc=True, root=folder, paper_size=PAPER,
                          borders=(MARGIN_PT, MARGIN_PT, -MARGIN_PT, -(MARGIN_PT + FOOTER_PT)))
        try:
            pdf.add_section(section, user_css=STYLESHEET)
            buffer = io.BytesIO()
            pdf.save_bytes(buffer)
        except Exception as exc:  # noqa: BLE001 - PyMuPDF raises plain RuntimeErrors
            raise ReportError(f"The PDF could not be written: {exc}") from exc
    return number_pages(buffer.getvalue())


def number_pages(pdf: bytes) -> bytes:
    """``pdf`` with "Page n of N" at the foot of every page, compressed."""
    import pymupdf

    document = pymupdf.open(stream=pdf, filetype="pdf")
    try:
        count = document.page_count
        grey = tuple(int(MUTED[i:i + 2], 16) / 255 for i in (1, 3, 5))
        for number, page in enumerate(document, start=1):
            box = pymupdf.Rect(MARGIN_PT, page.rect.height - MARGIN_PT, page.rect.width - MARGIN_PT,
                               page.rect.height - MARGIN_PT + FOOTER_PT)
            page.insert_textbox(box, f"Page {number} of {count}", fontsize=8, fontname="helv", color=grey,
                                align=pymupdf.TEXT_ALIGN_CENTER)
        return document.tobytes(garbage=3, deflate=True)
    finally:
        document.close()


# ----------------------------------------------------------------------------- the Markdown
def report_markdown(report: ReportDTO, folder: Path) -> str:
    """The whole report as Markdown (with HTML figures); the pictures are written to ``folder``."""
    parts = [figure_html(image, index, folder) for index, image in enumerate(report.images)]
    if report.note:
        parts.append(f'<p class="note">{html.escape(report.note)}</p>')
    parts.append(explanation_markdown(report.markdown))
    return "\n\n".join(parts)


def figure_html(image: ReportImageDTO, index: int, folder: Path) -> str:
    """One picture with its title and colour key, centred on the page, the key as wide as the picture."""
    width, height = picture_size(image.width, image.height)
    picture = f"layer-{index}.png"
    (folder / picture).write_bytes(image.png)
    left = (TEXT_WIDTH_PT - width) / 2
    lines = [f'<div class="figure" style="margin-left: {left:.2f}pt; width: {width:.2f}pt">',
             f'<p class="figure-title">{html.escape(image.title)}</p>',
             f'<img src="{picture}" style="width: {width:.2f}pt; height: {height:.2f}pt"/>']
    lines += colour_key_lines(image.colour_key, index, folder, width)
    lines.append("</div>")
    return "\n".join(lines)


def picture_size(pixels_wide: int, pixels_high: int) -> tuple[float, float]:
    """How large (in points) a picture is shown: as wide as fits, small ones enlarged, tall ones narrowed."""
    pixels_wide, pixels_high = max(1, pixels_wide), max(1, pixels_high)
    width = min(MAX_PICTURE_PT, max(MIN_PICTURE_PT, pixels_wide * 0.75))  # 0.75 pt per 96-dpi pixel
    height = width * pixels_high / pixels_wide
    if height > MAX_PICTURE_HEIGHT_PT:
        width, height = width * MAX_PICTURE_HEIGHT_PT / height, MAX_PICTURE_HEIGHT_PT
    return width, height


def colour_key_lines(legend: LegendDTO | None, index: int, folder: Path, width: float) -> list[str]:
    """A colour bar exactly ``width`` wide with its low and high values under its ends, or a swatch
    and name per class; nothing when there is no key."""
    if legend is None or not legend.colours:
        return []
    if legend.kind == "scale":
        bar = f"bar-{index}.png"
        (folder / bar).write_bytes(colour_bar_png(legend.colours))
        return [f'<img src="{bar}" style="width: {width:.2f}pt; height: {BAR_HEIGHT_PT}pt"/>',
                f'<table class="range" style="width: {width:.2f}pt"><tr>'
                f'<td class="low">{html.escape(format_number(legend.low))}</td>'
                f'<td class="high">{html.escape(format_number(legend.high))}</td></tr></table>']
    if legend.kind == "classes" and legend.labels:
        cells = "".join(f'<td class="swatch" style="background-color: {html.escape(colour)}">&#160;</td>'
                        f'<td>{html.escape(label)}</td>' for label, colour in zip(legend.labels, legend.colours))
        return [f'<table class="classes"><tr>{cells}</tr></table>']
    return []


def colour_bar_png(colours: tuple[str, ...]) -> bytes:
    """A horizontal colour bar blending smoothly through ``colours`` ("#RRGGBB") from left to right."""
    stops = np.array([[int(colour.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)] for colour in colours], float)
    positions = np.linspace(0, len(stops) - 1, BAR_PIXELS)
    left = np.minimum(positions.astype(int), max(0, len(stops) - 2))
    right = np.minimum(left + 1, len(stops) - 1)
    t = (positions - left)[:, None]
    row = np.round(stops[left] * (1 - t) + stops[right] * t).astype(np.uint8)
    rgba = np.concatenate([row, np.full((BAR_PIXELS, 1), 255, np.uint8)], axis=1)
    return rgba_to_png(np.repeat(rgba[None, :, :], 8, axis=0))


def format_number(value: float | None) -> str:
    """A range value as briefly as it reads well (e.g. -0.2, 0.8, 1,530, 4.5e-05)."""
    if value is None:
        return ""
    magnitude = abs(value)
    if magnitude >= 1000 or value == int(value):
        return f"{value:,.0f}"
    if magnitude >= 1:
        return f"{value:.2f}"
    if magnitude >= 0.001:
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return f"{value:.2g}"


# ----------------------------------------------------------------------------- the explanation
def explanation_markdown(markdown: str) -> str:
    """The explanation made ready for PyMuPDF's HTML engine: header-less tables get column names,
    long words (file names) may wrap, and each table stays on one page with the heading above it."""
    return keep_tables_together(breakable_long_words(name_blank_table_headers(markdown)))


LONG_WORD = re.compile(r"[^\s|<>`()\[\]]{40,}")
WORD_BREAK = '<span style="font-size: 0.1pt"> </span>'  # a space too small to see: a place to wrap


def breakable_long_words(markdown: str) -> str:
    """Let long words such as result file names wrap after their ``_``, ``/`` and ``\\``.

    The engine never breaks inside a word and has no glyph for a zero-width space, so a tiny space
    is put after those characters instead; it cannot be seen. Dates keep their ``-``. Links, code
    and tables are left alone: the engine sizes table columns well by itself, and break points in
    a cell would let it squeeze that column."""
    def soften(match: re.Match) -> str:
        word = match.group(0)
        if "://" in word or word.startswith("www."):
            return word
        return re.sub(r"([_/\\])", lambda char: char.group(1) + WORD_BREAK, word)
    lines = []
    in_code = False
    for line in markdown.split("\n"):
        if line.lstrip().startswith("```"):
            in_code = not in_code
        keep = in_code or _table_cells(line) is not None
        lines.append(line if keep else LONG_WORD.sub(soften, line))
    return "\n".join(lines)


KEEP_OPEN = ('<table class="keep" style="border: none; width: 100%; margin: 0"><tr>'
             '<td class="keep-cell" style="border: none; padding: 0">')
KEEP_CLOSE = "</td></tr></table>"
TABLE_WITH_HEADING = re.compile(r"(^#{1,6} [^\n]*\n\n)?((?:^\|[^\n]*\|[ \t]*(?:\n|$))+)", re.MULTILINE)


def keep_tables_together(markdown: str) -> str:
    """Wrap each table, with the heading just above it, in a one-cell table.

    The engine ignores ``page-break-inside: avoid`` and may leave a heading or a table's header row
    alone at the foot of a page; it does move a whole table row to the next page, so the wrapped
    heading and table go together. Blank lines around them keep them read as Markdown."""
    return TABLE_WITH_HEADING.sub(
        lambda match: f"{KEEP_OPEN}\n\n{match.group(1) or ''}{match.group(2).rstrip()}\n\n{KEEP_CLOSE}\n", markdown)


# ----------------------------------------------------------------------------- tables
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
