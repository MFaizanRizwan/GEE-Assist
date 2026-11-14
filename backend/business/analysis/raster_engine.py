"""Runs analysis layers over downloaded GeoTIFFs, a block of rows at a time.

Downloads can be several gigabytes, so nothing reads a whole file: each block of rows
is read, scaled to physical units (``sensors.scaling``), moved to the compute device
(GPU or CPU, see ``compute_device``), turned into the requested layers, summarised,
brought back and written to the result GeoTIFF.

Several datasets (time periods) can take part. They are ordered by date, oldest
first; the latest is "now" and the oldest "before". The first dataset given sets the
grid: the others are resampled onto it (nearest neighbour) when theirs differs.

Two passes are made when a layer needs the whole dataset first (e.g. VCI needs the
lowest and highest NDVI, PCA the band covariance): the first pass only feeds the
``ScenePass`` objects, the second computes and writes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

from backend.business.analysis.compute_device import ComputeBackend
from backend.business.analysis.sensors import NODATA, scaling
from backend.dto.download_dto import DatasetDTO
from backend.dto.result_dto import ResultLayerDTO
from backend.exceptions import AnalysisError

EARTH_RADIUS_KM = 6371.0088
DEFAULT_BLOCK_ROWS = 1024

Progress = Callable[[float], None]


@dataclass
class Period:
    """One dataset taking part in an analysis."""

    dataset: DatasetDTO
    satellite: str
    band_names: tuple[str, ...]
    roles: dict[str, str]                       # role -> band name
    date: str = ""                              # start date "YYYY-MM-DD", for ordering ("" = unknown)

    @property
    def label(self) -> str:
        return " to ".join(d for d in (self.dataset.start_date, self.dataset.end_date) if d) or \
            Path(self.dataset.path).stem


@dataclass
class LayerSpec:
    """One output band: how to compute it for a block, and how to show it."""

    key: str
    label: str
    compute: Callable[["Block"], Any]
    style: str = "diverging"
    unit: str = ""
    low: float | None = None
    high: float | None = None
    classes: str = ""
    stats: bool = True                          # add mean / min / max / std to the metrics

    def to_dto(self) -> ResultLayerDTO:
        return ResultLayerDTO(self.key, self.label, self.style, self.unit, self.low, self.high, self.classes)


class ScenePass:
    """Sees every block in a first pass; ``result()`` is then given to layers as ``scene[name]``."""

    name = ""

    def add(self, block: "Block") -> None:
        raise NotImplementedError

    def result(self) -> Any:
        raise NotImplementedError


class MinMaxPass(ScenePass):
    """Lowest and highest finite value of a quantity over the dataset."""

    def __init__(self, name: str, compute: Callable[["Block"], Any]):
        self.name, self._compute = name, compute
        self.low, self.high = math.inf, -math.inf

    def add(self, block: "Block") -> None:
        values = block.finite(self._compute(block))
        if values.size:
            self.low = min(self.low, block.backend.scalar(block.xp.min(values)))
            self.high = max(self.high, block.backend.scalar(block.xp.max(values)))

    def result(self) -> tuple[float, float]:
        if self.low > self.high:
            raise AnalysisError(f"The dataset has no valid {self.name} values.")
        return self.low, self.high


class Accumulator:
    """Sees every block of the second pass with its computed layers; adds numbers to the metrics."""

    def add(self, block: "Block", outputs: dict[str, Any]) -> None:
        raise NotImplementedError

    def metrics(self) -> dict[str, float]:
        raise NotImplementedError


class _Stats(Accumulator):
    def __init__(self, layer: LayerSpec):
        self.layer = layer
        self.count, self.total, self.squares = 0, 0.0, 0.0
        self.low, self.high = math.inf, -math.inf

    def add(self, block: "Block", outputs: dict[str, Any]) -> None:
        xp, values = block.xp, block.finite(outputs[self.layer.key])
        if not values.size:
            return
        values64 = values.astype(xp.float64)
        self.count += int(values.size)
        self.total += block.backend.scalar(xp.sum(values64))
        self.squares += block.backend.scalar(xp.sum(values64 * values64))
        self.low = min(self.low, block.backend.scalar(xp.min(values)))
        self.high = max(self.high, block.backend.scalar(xp.max(values)))

    def metrics(self) -> dict[str, float]:
        if not self.count:
            return {}
        mean = self.total / self.count
        std = math.sqrt(max(self.squares / self.count - mean * mean, 0.0))
        unit = f" ({self.layer.unit})" if self.layer.unit else ""
        name = self.layer.label
        return {f"{name} mean{unit}": mean, f"{name} min{unit}": self.low, f"{name} max{unit}": self.high,
                f"{name} std{unit}": std}


class Block:
    """A strip of rows of every period, read on demand, on the compute device."""

    def __init__(self, engine: "RasterEngine", row: int, height: int, params: dict, scene: dict):
        self.engine = engine
        self.backend = engine.backend
        self.xp = engine.backend.xp
        self.row, self.height = row, height
        self.params = {**params, "scene": scene}
        self.scene = scene
        self._cache: dict[tuple[int, str], Any] = {}

    # ---- bands
    def band(self, name: str, period: int = -1, scaled: bool = True):
        """One band of a period (-1 = latest) as float32 on the device; no-data is NaN."""
        index = period % len(self.engine.periods)
        key = (index, f"{name}:{scaled}")
        if key not in self._cache:
            self._cache[key] = self.backend.to_device(self.engine.read(index, name, self.row, self.height, scaled))
        return self._cache[key]

    def roles(self, period: int = -1) -> dict[str, Any]:
        """Role -> array, read lazily: only the roles a formula uses are read."""
        return _LazyRoles(self, period)

    def before(self) -> dict[str, Any]:
        return self.roles(0)

    @property
    def pixel_area_km2(self):
        """Area of each pixel of the block (a column: rows differ in latitude)."""
        rows = self.engine.row_areas_km2[self.row:self.row + self.height]
        return self.backend.to_device(rows.reshape(-1, 1))

    def finite(self, array):
        return array[self.xp.isfinite(array)]

    def clean(self, array):
        """Float32 with every non-finite value as NaN."""
        array = self.xp.asarray(array, dtype=self.xp.float32)
        return self.xp.where(self.xp.isfinite(array), array, self.xp.float32(np.nan))


class _LazyRoles(dict):
    def __init__(self, block: Block, period: int):
        super().__init__()
        self._block, self._period = block, period
        self._roles = block.engine.periods[period].roles

    def __missing__(self, role: str):
        band = self._roles.get(role)
        if band is None:
            raise AnalysisError(f"The dataset has no {role.upper()} band.")
        value = self._block.band(band, self._period)
        self[role] = value
        return value


class RasterEngine:
    def __init__(self, periods: list[Period], backend: ComputeBackend, block_rows: int = DEFAULT_BLOCK_ROWS):
        if not periods:
            raise AnalysisError("Choose a dataset to analyse.")
        self.reference = periods[0]
        dated = sorted(enumerate(periods), key=lambda item: (item[1].date or "9999", item[0]))
        if all(period.date for period in periods):
            self.periods = [period for _, period in dated]
        else:  # without dates: as given, with the chosen dataset as the latest
            self.periods = periods[1:] + periods[:1]
        self.backend = backend
        self.block_rows = max(16, block_rows)
        self._sources: list[Any] = []
        self.width = self.height = 0
        self.crs = self.transform = None
        self.row_areas_km2 = np.zeros(0)

    # ---- files
    def __enter__(self) -> "RasterEngine":
        import rasterio
        from rasterio.vrt import WarpedVRT

        try:
            ref = rasterio.open(self.reference.dataset.path)
        except rasterio.errors.RasterioIOError as exc:
            raise AnalysisError(f"Cannot open {Path(self.reference.dataset.path).name}: it is missing or not a "
                                "GeoTIFF.") from exc
        self.width, self.height, self.crs, self.transform = ref.width, ref.height, ref.crs, ref.transform
        ref.close()
        for period in self.periods:
            try:
                src = rasterio.open(period.dataset.path)
            except rasterio.errors.RasterioIOError as exc:
                raise AnalysisError(f"Cannot open {Path(period.dataset.path).name}.") from exc
            same_grid = (src.width, src.height, src.transform) == (self.width, self.height, self.transform) \
                and src.crs == self.crs
            if not same_grid:
                if src.crs is None or self.crs is None:
                    raise AnalysisError(f"{Path(period.dataset.path).name} has no coordinates, so it cannot be "
                                        "lined up with the other dataset.")
                src = WarpedVRT(src, crs=self.crs, transform=self.transform, width=self.width,
                                height=self.height, src_nodata=src.nodata, nodata=NODATA)
            self._sources.append(src)
        self.row_areas_km2 = self._row_areas()
        return self

    def __exit__(self, *exc) -> None:
        for src in self._sources:
            src.close()
        self._sources = []
        self.backend.free()

    def read(self, period: int, band: str, row: int, height: int, scaled: bool = True) -> np.ndarray:
        from rasterio.windows import Window

        src = self._sources[period]
        names = self.periods[period].band_names
        if band not in names:
            raise AnalysisError(f"{Path(self.periods[period].dataset.path).name} has no band {band}.")
        data = src.read(names.index(band) + 1, window=Window(0, row, self.width, height), out_dtype="float32")
        invalid = ~np.isfinite(data) | (data == NODATA)
        if src.nodata is not None and not math.isnan(src.nodata):
            invalid |= data == np.float32(src.nodata)
        if scaled:
            scale, offset = scaling(self.periods[period].satellite, band)
            if (scale, offset) != (1.0, 0.0):
                data = data * np.float32(scale) + np.float32(offset)
        data[invalid] = np.nan
        return data

    def _row_areas(self) -> np.ndarray:
        """km² of one pixel in each row."""
        a, e = self.transform.a, self.transform.e
        if self.crs is not None and self.crs.is_geographic:
            top = self.transform.f
            edges = np.radians(top + e * np.arange(self.height + 1))
            widths = math.radians(abs(a))
            return EARTH_RADIUS_KM ** 2 * widths * np.abs(np.sin(edges[:-1]) - np.sin(edges[1:]))
        unit = 1.0
        if self.crs is not None and self.crs.linear_units_factor:
            unit = self.crs.linear_units_factor[1]  # metres per unit
        return np.full(self.height, abs(a * e) * unit * unit / 1e6)

    def blocks(self):
        for row in range(0, self.height, self.block_rows):
            yield row, min(self.block_rows, self.height - row)

    # ---- running
    def run(
        self,
        layers: list[LayerSpec],
        output_path: str,
        params: Optional[dict] = None,
        scene_passes: Optional[list[ScenePass]] = None,
        accumulators: Optional[list[Accumulator]] = None,
        on_progress: Optional[Progress] = None,
    ) -> dict[str, float]:
        """Compute ``layers`` into ``output_path`` (one band each); returns the metrics."""
        import rasterio

        if not layers:
            raise AnalysisError("Choose at least one process to run.")
        params = dict(params or {})
        scene: dict[str, Any] = {}
        scene_passes = scene_passes or []
        steps = len(list(self.blocks())) * (2 if scene_passes else 1)
        done = 0
        old_settings = np.seterr(all="ignore")  # divisions by zero become no-data, not warnings
        try:
            if scene_passes:
                for row, height in self.blocks():
                    block = Block(self, row, height, params, scene)
                    for scene_pass in scene_passes:
                        scene_pass.add(block)
                    done += 1
                    _report(on_progress, done / steps)
                for scene_pass in scene_passes:
                    scene[scene_pass.name] = scene_pass.result()

            stats = [_Stats(layer) for layer in layers if layer.stats]
            everyone = stats + list(accumulators or [])
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            profile = dict(driver="GTiff", width=self.width, height=self.height, count=len(layers), dtype="float32",
                           crs=self.crs, transform=self.transform, nodata=NODATA, compress="deflate", tiled=True,
                           blockxsize=256, blockysize=256, BIGTIFF="IF_SAFER")
            if self.width < 256 or self.height < 256:
                profile.update(tiled=False)
                profile.pop("blockxsize")
                profile.pop("blockysize")
            with rasterio.open(output_path, "w", **profile) as dst:
                for index, layer in enumerate(layers, start=1):
                    dst.set_band_description(index, layer.key)
                for row, height in self.blocks():
                    block = Block(self, row, height, params, scene)
                    outputs = {layer.key: block.clean(layer.compute(block)) for layer in layers}
                    for accumulator in everyone:
                        accumulator.add(block, outputs)
                    from rasterio.windows import Window

                    window = Window(0, row, self.width, height)
                    for index, layer in enumerate(layers, start=1):
                        host = self.backend.to_host(outputs[layer.key]).astype(np.float32, copy=False)
                        dst.write(np.where(np.isnan(host), np.float32(NODATA), host), index, window=window)
                    done += 1
                    _report(on_progress, done / steps)
        finally:
            np.seterr(**old_settings)
        metrics: dict[str, float] = {}
        for accumulator in everyone:
            metrics.update(accumulator.metrics())
        return metrics


def _report(on_progress: Optional[Progress], fraction: float) -> None:
    if on_progress is not None:
        on_progress(min(1.0, fraction))
