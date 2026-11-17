"""DTOs for UC-08 Get AI Explanation: what is sent to Gemini about an analysis, and its answer.

``RasterMetadataDTO`` describes a GeoTIFF: the dataset before the analysis (and any
earlier dataset it was compared with) and the result GeoTIFF after it.
``ExplanationRequestDTO`` is everything Gemini is given: which analysis ran, with which
settings, the metadata before and after, the numbers, the saved result GeoTIFF and a
PNG preview of each of its layers. ``ExplanationDTO`` is Gemini's answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.dto.result_dto import ResultDTO


@dataclass(frozen=True)
class RasterMetadataDTO:
    """What a GeoTIFF holds and covers, read from the file (and its download name)."""

    name: str                                   # file name without ".tif"
    path: str
    satellite: str = ""                         # e.g. "Sentinel-2"
    start_date: str = ""                        # "YYYY-MM-DD"
    end_date: str = ""
    bands: tuple[str, ...] = ()
    width: int = 0                              # pixels
    height: int = 0
    crs: str = ""                               # e.g. "EPSG:4326"
    bounds: tuple[float, float, float, float] | None = None  # west, south, east, north (degrees)
    pixel_size_m: float | None = None           # approximate ground size of one pixel
    area_km2: float | None = None               # approximate area covered
    dtype: str = ""
    nodata: float | None = None
    size_bytes: int = 0

    @property
    def centre(self) -> tuple[float, float] | None:
        """(longitude, latitude) of the middle of the area."""
        if self.bounds is None:
            return None
        west, south, east, north = self.bounds
        return (west + east) / 2, (south + north) / 2

    def rows(self) -> list[tuple[str, str]]:
        """(label, value) pairs for what is known, in reading order (shown in the app and sent to Gemini)."""
        rows: list[tuple[str, str]] = [("File", f"{self.name}.tif")]
        if self.satellite:
            rows.append(("Satellite", self.satellite))
        dates = " to ".join(d for d in (self.start_date, self.end_date) if d)
        if dates:
            rows.append(("Dates", dates))
        if self.bands:
            rows.append((f"Bands ({len(self.bands)})", ", ".join(self.bands)))
        if self.width and self.height:
            rows.append(("Size", f"{self.width} × {self.height} pixels"))
        if self.pixel_size_m:
            rows.append(("Pixel size", f"about {self.pixel_size_m:,.0f} m"))
        if self.crs:
            rows.append(("Coordinate system", self.crs))
        if self.bounds is not None:
            west, south, east, north = self.bounds
            rows.append(("Bounds (W, S, E, N)", f"{west:.4f}, {south:.4f}, {east:.4f}, {north:.4f}"))
            lon, lat = self.centre or (0.0, 0.0)
            rows.append(("Centre (lat, lon)", f"{lat:.4f}, {lon:.4f}"))
        if self.area_km2:
            rows.append(("Area", f"about {self.area_km2:,.1f} km²"))
        if self.dtype:
            rows.append(("Data type", self.dtype))
        if self.nodata is not None:
            rows.append(("No-data value", f"{self.nodata:g}"))
        if self.size_bytes:
            rows.append(("File size", _size(self.size_bytes)))
        return rows


@dataclass(frozen=True)
class ProcessInfoDTO:
    """One process that ran, as the formula table describes it."""

    key: str                                    # e.g. "NDVI"
    name: str = ""                              # e.g. "Normalized Difference Vegetation Index"
    formula: str = ""
    value_range: str = ""
    interpretation: str = ""


@dataclass(frozen=True)
class LayerInfoDTO:
    """One band of the result GeoTIFF and how its preview is coloured."""

    key: str                                    # band name, e.g. "NDVI"
    label: str
    unit: str = ""
    legend: str = ""                            # e.g. "red to green over -0.2 to 0.8"


@dataclass(frozen=True)
class ExplanationRequestDTO:
    """Everything Gemini is given to explain one analysis result."""

    result: ResultDTO                           # saved: its GeoTIFF is in the project's analysis folder
    category: str                               # "Water", "Vegetation", "LST" or "LULC"
    category_label: str = ""                    # e.g. "Land Surface Temperature"
    processes: tuple[ProcessInfoDTO, ...] = ()
    params: dict[str, Any] = field(default_factory=dict)
    before: RasterMetadataDTO | None = None     # the dataset analysed
    compared_with: tuple[RasterMetadataDTO, ...] = ()  # earlier datasets (before / after processes)
    after: RasterMetadataDTO | None = None      # the result GeoTIFF
    layers: tuple[LayerInfoDTO, ...] = ()
    previews: tuple[bytes, ...] = ()            # PNG of each layer, in the order of ``layers``

    @property
    def tif_path(self) -> str:
        return self.result.output_path


@dataclass(frozen=True)
class ExplanationDTO:
    """Gemini's explanation of an analysis result."""

    text: str                                   # Markdown
    model: str = ""                             # the Gemini model that answered
    tif_attached: bool = True                   # False: Gemini refused the GeoTIFF; only previews were sent
    request: ExplanationRequestDTO | None = None
    saved_path: str = ""                        # the explanation kept in the project's explanation folder (.md)
    created_at: str = ""                        # ISO timestamp
    previews_attached: bool = True              # False: Gemini refused the previews too; only the metadata


def _size(size: int) -> str:
    value = float(size)
    for unit in ("bytes", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:,.0f} {unit}" if unit == "bytes" else f"{value:,.1f} {unit}"
        value /= 1024
    return f"{size} bytes"
