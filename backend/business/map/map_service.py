"""Class diagram: MapService. Reads downloaded GeoTIFFs so they can be looked at."""

from __future__ import annotations

from pathlib import Path

from backend.business.download.naming import parse_dataset_name
from backend.business.map import layer_styles, raster_renderer
from backend.business.map.i_map_service import IMapService
from backend.business.map.result_styles import read_result_layers
from backend.business.map.view_presets import presets_for
from backend.dto.map_dto import MapLayerDTO, RasterInfoDTO, RasterViewDTO, ViewPresetDTO
from backend.dto.result_dto import ResultDTO
from backend.exceptions import MapError


class MapService(IMapService):
    def describe(self, path: str) -> RasterInfoDTO:
        import rasterio
        from rasterio.warp import transform_bounds

        file = Path(path)
        try:
            with rasterio.open(file) as src:
                names = tuple(name or f"Band {index}" for index, name in enumerate(src.descriptions, start=1))
                bounds = tuple(src.bounds)
                if src.crs and src.crs.to_epsg() != 4326:
                    bounds = transform_bounds(src.crs, "EPSG:4326", *bounds, densify_pts=21)
                satellite, start, end = parse_dataset_name(file.stem)
                return RasterInfoDTO(
                    path=str(file), name=file.stem, width=src.width, height=src.height, band_names=names,
                    crs=src.crs.to_string() if src.crs else "", bounds=tuple(float(v) for v in bounds),
                    nodata=src.nodata, dtype=src.dtypes[0], size_bytes=file.stat().st_size,
                    satellite=satellite, start_date=start, end_date=end,
                    result_layers=read_result_layers(file, names),
                )
        except rasterio.errors.RasterioIOError as exc:
            raise MapError(f"Cannot open {file.name}: it is missing or not a GeoTIFF.") from exc

    def view_presets(self, info: RasterInfoDTO, analysis_colours: bool = True) -> list[ViewPresetDTO]:
        return presets_for(info, analysis_colours)

    def render(self, info: RasterInfoDTO, preset: ViewPresetDTO, max_size: int = 1600) -> RasterViewDTO:
        return raster_renderer.render(info, preset, max_size)

    def values_at(self, info: RasterInfoDTO, lon: float, lat: float) -> dict[str, float | None]:
        import rasterio
        from rasterio.warp import transform
        from rasterio.windows import Window

        empty: dict[str, float | None] = {band: None for band in info.band_names}
        try:
            with rasterio.open(info.path) as src:
                x, y = lon, lat
                if src.crs and src.crs.to_epsg() != 4326:
                    xs, ys = transform("EPSG:4326", src.crs, [lon], [lat])
                    x, y = xs[0], ys[0]
                row, col = src.index(x, y)
                if not (0 <= row < src.height and 0 <= col < src.width):
                    return empty
                pixel = src.read(window=Window(col, row, 1, 1))[:, 0, 0]
        except rasterio.errors.RasterioIOError as exc:
            raise MapError(f"Cannot read {info.name}: {exc}") from exc
        return {band: (None if _missing(value, info.nodata) else float(value))
                for band, value in zip(info.band_names, pixel)}

    def build_layers(self, result: ResultDTO, max_size: int = 1600) -> list[MapLayerDTO]:
        import math

        import numpy as np
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.warp import transform_bounds

        try:
            with rasterio.open(result.output_path) as src:
                scale = max(1.0, max(src.width, src.height) / max_size)
                height, width = max(1, math.ceil(src.height / scale)), max(1, math.ceil(src.width / scale))
                bounds = tuple(src.bounds)
                if src.crs and src.crs.to_epsg() != 4326:
                    bounds = transform_bounds(src.crs, "EPSG:4326", *bounds, densify_pts=21)
                names = list(src.descriptions)
                layers = []
                for layer in result.layers:
                    if layer.key not in names:
                        continue
                    categorical = layer.style in ("mask", "classes", "transition")
                    values = src.read(names.index(layer.key) + 1, out_shape=(height, width), out_dtype="float64",
                                      resampling=Resampling.nearest if categorical else Resampling.average)
                    valid = np.isfinite(values) & (values != src.nodata if src.nodata is not None else True)
                    title = f"{layer.label} ({layer.unit})" if layer.unit else layer.label
                    rgb, legend = layer_styles.draw(values, valid, layer.style, title, layer.low, layer.high,
                                                    layer.classes)
                    rgba = np.dstack([rgb, np.where(valid, 255, 0).astype(np.uint8)])
                    extra = _layer_data(values, valid, rgb, legend)
                    layers.append(MapLayerDTO(layer.key, layer.label, layer.style, rgba, legend, width, height,
                                              tuple(float(v) for v in bounds), scale, **extra))
                return layers
        except rasterio.errors.RasterioIOError as exc:
            raise MapError(f"Cannot open the analysis result {Path(result.output_path).name}.") from exc


def _missing(value: float, nodata: float | None) -> bool:
    return bool(value != value) or (nodata is not None and value == nodata)  # NaN, or the no-data value


def _layer_data(values, valid, rgb, legend) -> dict:
    """Raw values + statistics (continuous layers) or class fractions (categorical), for live symbology."""
    import numpy as np

    if legend.kind == "scale":
        sample = values[valid]
        if sample.size:
            lo2, hi2 = (float(v) for v in np.percentile(sample, (2.0, 98.0)))
            stats = {
                "min": float(sample.min()), "max": float(sample.max()),
                "mean": float(sample.mean()), "std": float(sample.std()),
                "p2": lo2, "p98": hi2,
            }
            counts, edges = np.histogram(sample, bins=40)
            histogram = (counts.astype(int).tolist(), [float(e) for e in edges])
        else:
            stats, histogram = {}, ()
        return {
            "kind": "scale",
            "values": np.where(valid, values, np.nan).astype(np.float32),
            "stats": stats,
            "histogram": histogram,
        }

    # Categorical: the fraction of valid pixels matching each legend colour.
    total = int(valid.sum()) or 1
    fractions = []
    for label, colour in zip(legend.labels, legend.colours):
        r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
        mask = valid & (rgb[..., 0] == r) & (rgb[..., 1] == g) & (rgb[..., 2] == b)
        fractions.append((label, colour, float(int(mask.sum()) / total)))
    return {"kind": "classes", "class_fractions": tuple(fractions)}
