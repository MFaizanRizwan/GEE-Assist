"""The "Source dataset" card of the modern Downloads page: what a download fetches and where.

Shows the satellite and collection, the area with its dates, resolution, cloud limit, bands and
projection, and the area's outline: its number of vertices, bounding box and each vertex's
coordinates. Colours come from the page stylesheet (object names only).
"""

from __future__ import annotations

import json
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from backend.config import get_dataset
from backend.dto import DownloadJobDTO
from frontend.aoi_geometry import bbox_of, polygon_from_geojson
from frontend.download_format import format_size
from frontend.widgets.download_rows import SATELLITE

NONE = "–"
VISIBLE_VERTICES = 8


def outline_vertices(aoi: str) -> list[tuple[float, float]]:
    """The distinct (lon, lat) vertices of the area's outer ring(s); empty if there is no usable polygon."""
    try:
        geometry = polygon_from_geojson(aoi)
        coords = geometry["coordinates"]
        polygons = [coords] if geometry["type"] == "Polygon" else coords if geometry["type"] == "MultiPolygon" else []
        vertices = []
        for polygon in polygons:
            ring = polygon[0] if polygon else []
            if len(ring) > 1 and ring[0] == ring[-1]:
                ring = ring[:-1]          # the closing position repeats the first vertex
            vertices.extend((float(p[0]), float(p[1])) for p in ring)
        return vertices
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, json.JSONDecodeError):
        return []


def _bbox(aoi: str) -> list[float] | None:
    try:
        return bbox_of(polygon_from_geojson(aoi))
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, json.JSONDecodeError):
        return None


class SourceCard(QFrame):
    """Describes the source of one download (the running one, or the latest)."""

    FIELDS = ("AREA", "DATES", "RESOLUTION", "CLOUD COVER", "BANDS", "PROJECTION")

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("SideCard")
        self._shown: tuple[Any, ...] | None = None

        title = QLabel("Source dataset", objectName="CardTitle")
        self.empty = QLabel("Start a download from Query Input to see its source here.", objectName="Muted")
        self.empty.setWordWrap(True)

        # ---- the satellite
        hero = QFrame(objectName="SourceHero")
        icon = QLabel(SATELLITE, objectName="SatelliteIcon")
        icon.setFixedSize(36, 36)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.satellite = QLabel(objectName="JobTitle")
        self.collection = QLabel(objectName="SourceSub")
        self.collection.setWordWrap(True)
        names = QVBoxLayout()
        names.setSpacing(1)
        names.addWidget(self.satellite)
        names.addWidget(self.collection)
        hero_row = QHBoxLayout()
        hero_row.setSpacing(10)
        hero_row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        hero_row.addLayout(names, 1)

        # ---- what and when: AREA and DATES take a whole row, the rest two per row
        self.values: dict[str, QLabel] = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        positions = {"AREA": (0, 0, 1, 2), "DATES": (1, 0, 1, 2), "RESOLUTION": (2, 0, 1, 1),
                     "CLOUD COVER": (2, 1, 1, 1), "BANDS": (3, 0, 1, 1), "PROJECTION": (3, 1, 1, 1)}
        for name in self.FIELDS:
            cell = QVBoxLayout()
            cell.setSpacing(2)
            cell.addWidget(QLabel(name, objectName="StatName"))
            value = QLabel(NONE, objectName="SourceValue")
            value.setWordWrap(True)
            cell.addWidget(value)
            self.values[name] = value
            grid.addLayout(cell, *positions[name])

        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(12, 12, 12, 12)
        hero_layout.setSpacing(12)
        hero_layout.addLayout(hero_row)
        hero_layout.addLayout(grid)

        # ---- the area's outline
        self.vertex_count = QLabel(NONE, objectName="SourceValue")
        count_row = QHBoxLayout()
        count_row.addWidget(QLabel("VERTICES", objectName="StatName"))
        count_row.addStretch(1)
        count_row.addWidget(self.vertex_count)
        self.bounds = QLabel(objectName="Coordinates")
        self.bounds.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.coordinates = QLabel(objectName="Coordinates")
        self.coordinates.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.coordinates.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.coordinates_scroll = QScrollArea(objectName="CoordinateList")
        self.coordinates_scroll.setWidgetResizable(True)
        self.coordinates_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.coordinates_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.coordinates_scroll.setWidget(self.coordinates)

        # ---- size of the package
        self.size = QLabel(NONE, objectName="SourceTotal")
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Package size", objectName="Muted"))
        size_row.addStretch(1)
        size_row.addWidget(self.size)

        self.details = QWidget()
        details = QVBoxLayout(self.details)
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(10)
        details.addWidget(hero)
        details.addLayout(count_row)
        details.addWidget(QLabel("BOUNDING BOX", objectName="StatName"))
        details.addWidget(self.bounds)
        details.addWidget(QLabel("COORDINATES  (LON, LAT)", objectName="StatName"))
        details.addWidget(self.coordinates_scroll)
        line = QFrame(objectName="CardLine")
        line.setFixedHeight(1)
        details.addWidget(line)
        details.addLayout(size_row)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(self.empty)
        layout.addWidget(self.details)
        self.show_job(None)

    def show_job(self, job: DownloadJobDTO | None) -> None:
        request = job.request if job else None
        key = (job.id, job.total_bytes) if job else None
        if key == self._shown:
            return  # unchanged: keep the coordinate list where the user scrolled it
        self._shown = key
        self.empty.setVisible(request is None)
        self.details.setVisible(request is not None)
        if request is None:
            return

        info = get_dataset(request.dataset)
        self.satellite.setText(info.satellite if info and info.satellite else request.dataset or job.name)
        self.collection.setText(info.collection_id if info else request.dataset)
        self.collection.setToolTip(info.name if info else "")
        dates = f"{request.start_date.isoformat()} → {request.end_date.isoformat()}" \
            if request.start_date and request.end_date else NONE
        scale = request.scale or (info.default_scale if info else None)
        bands = request.bands or (job.chunks[0].bands if job.chunks else [])
        values = {
            "AREA": request.aoi_name or "Custom area",
            "DATES": dates,
            "RESOLUTION": f"{scale} m" if scale else NONE,
            "CLOUD COVER": f"≤ {request.max_cloud_cover}%" if request.max_cloud_cover is not None else NONE,
            "BANDS": str(len(bands)) if bands else NONE,
            "PROJECTION": request.crs or NONE,
        }
        for name, value in values.items():
            self.values[name].setText(value)
        self.values["BANDS"].setToolTip(", ".join(bands))

        vertices = outline_vertices(request.aoi)
        self.vertex_count.setText(str(len(vertices)) if vertices else NONE)
        box = _bbox(request.aoi) if vertices else None
        self.bounds.setText(
            f"W {box[0]:.5f}   S {box[1]:.5f}\nE {box[2]:.5f}   N {box[3]:.5f}" if box else NONE
        )
        width = len(str(len(vertices)))
        self.coordinates.setText(
            "\n".join(f"{i:>{width}}   {lon:.5f}, {lat:.5f}" for i, (lon, lat) in enumerate(vertices, 1)) or NONE
        )
        # tall enough for every vertex up to VISIBLE_VERTICES rows; longer outlines scroll
        rows = min(max(len(vertices), 1), VISIBLE_VERTICES)
        self.coordinates.ensurePolished()  # measure with the stylesheet's mono font
        self.coordinates_scroll.setFixedHeight(self.coordinates.fontMetrics().lineSpacing() * rows + 26)
        self.size.setText(format_size(job.total_bytes) if job.total_bytes else NONE)
