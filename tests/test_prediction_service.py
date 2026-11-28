"""The prediction service on small synthetic GeoTIFFs whose answers are known."""

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
pytest.importorskip("sklearn")

from rasterio.transform import from_origin  # noqa: E402

from backend.business.prediction import PredictionService  # noqa: E402
from backend.business.prediction import algorithms as algo  # noqa: E402
from backend.dto.prediction_dto import (  # noqa: E402
    ANOMALY,
    CHANGE,
    CLASSIFY,
    FORECAST,
    PredictionInputDTO,
    PredictionOptionsDTO,
    PredictionProgress,
    PredictionRequestDTO,
)
from backend.exceptions import PredictionError  # noqa: E402

SIZE = 40
DATES = ["2020-06-01", "2021-06-01", "2022-06-01", "2023-06-01", "2024-06-01"]


def _write(path, layers, names, dtype="float32", nodata=-9999.0):
    layers = [np.asarray(layer, dtype=dtype) for layer in layers]
    with rasterio.open(str(path), "w", driver="GTiff", width=SIZE, height=SIZE, count=len(layers), dtype=dtype,
                       crs="EPSG:4326", transform=from_origin(73.0, 32.0, 0.001, 0.001), nodata=nodata) as dst:
        for i, (layer, name) in enumerate(zip(layers, names), start=1):
            dst.write(layer, i)
            dst.set_band_description(i, name)
    return str(path)


def _ndvi_series(tmp_path):
    """NDVI rising 0.05 a year on the left half, falling 0.03 on the right, with a little noise."""
    rng = np.random.default_rng(1)
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    base = 0.3 + 0.2 * yy / SIZE
    rate = np.where(xx < SIZE // 2, 0.05, -0.03)
    files = []
    for year, day in enumerate(DATES):
        ndvi = base + rate * year + rng.normal(0, 0.005, (SIZE, SIZE))
        files.append(PredictionInputDTO(_write(tmp_path / f"ndvi_{day}.tif", [ndvi], ["NDVI"]), day))
    return files, base + rate * 5   # the truth a year after the present


def _options(**kw):
    return PredictionOptionsDTO(sample_size=3000, working_size=64, **kw)


def test_every_algorithm_is_listed_with_whether_it_can_run():
    service = PredictionService()
    for task in (FORECAST, CHANGE, CLASSIFY, ANOMALY):
        listed = service.algorithms(task)
        assert listed and all(a.available for a in listed)   # every library is installed here
    keys = {a.key for a in service.algorithms(FORECAST)}
    assert {"persistence", "trend", "linear", "random_forest", "xgboost", "lightgbm", "torch_lstm",
            "gaussian_process", "svm"} <= keys
    assert {"torch_lstm", "torch_tcn", "no_change"}.isdisjoint(a.key for a in service.algorithms(CLASSIFY))
    assert "no_change" in {a.key for a in service.algorithms(CHANGE)}


def test_a_forecast_ranks_models_and_the_trend_beats_persistence(tmp_path):
    inputs, truth = _ndvi_series(tmp_path)
    request = PredictionRequestDTO(FORECAST, inputs, band="NDVI", target_date="2025-06-01",
                                   algorithms=["persistence", "trend", "linear", "random_forest", "torch_lstm"],
                                   options=_options(lags=3))
    result = PredictionService().run(request)
    by_key = {s.key: s for s in result.scores}
    assert all(not s.error for s in result.scores), [(s.key, s.error) for s in result.scores]
    assert result.primary_metric == "RMSE" and not result.higher_is_better
    assert by_key["trend"].metrics["RMSE"] < by_key["persistence"].metrics["RMSE"]
    assert [s.rank for s in result.scores if s.rank] == list(range(1, len([s for s in result.scores if s.rank]) + 1))
    best = result.best
    assert best.prediction.shape == (SIZE, SIZE)
    assert np.nanmean(np.abs(by_key["trend"].prediction - truth)) < 0.02   # a year ahead, from the trend
    assert result.uncertainty is not None and "ensemble" in by_key
    assert "Trained on the dates before the present" in result.validation


def test_a_forecast_needs_a_later_target_date(tmp_path):
    inputs, _ = _ndvi_series(tmp_path)
    with pytest.raises(PredictionError, match="after the present"):
        PredictionService().run(PredictionRequestDTO(FORECAST, inputs, band="NDVI", target_date="2023-01-01",
                                                     algorithms=["linear"], options=_options()))


def test_future_land_cover_learns_a_growing_town(tmp_path):
    """Built area (6) spreads one ring of cells a year around a centre; the rest is crops (4)."""
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    distance = np.hypot(yy - SIZE / 2, xx - SIZE / 2)
    inputs = []
    for year, day in enumerate(DATES):
        classes = np.where(distance < 5 + 3 * year, 6, 4)
        inputs.append(PredictionInputDTO(_write(tmp_path / f"lc_{day}.tif", [classes], ["label"], "uint8", 255),
                                         day))
    request = PredictionRequestDTO(CHANGE, inputs, band="label", target_date="2025-06-01",
                                   algorithms=["no_change", "random_forest", "logistic"],
                                   options=_options(lags=2, neighbourhood=2))
    result = PredictionService().run(request)
    by_key = {s.key: s for s in result.scores}
    assert not by_key["random_forest"].error
    assert by_key["random_forest"].metrics["F1 (macro)"] > by_key["no_change"].metrics["F1 (macro)"]
    future = by_key["random_forest"].prediction
    grows = int((future == 6).sum()) > int((np.where(distance < 5 + 3 * 4, 6, 4) == 6).sum())
    assert grows                                                           # the town keeps growing
    assert {name for _c, name, _col in result.classes} == {"Crops", "Built area"}   # Dynamic World names


def test_classify_the_present_image_from_a_class_raster(tmp_path):
    rng = np.random.default_rng(3)
    truth = (np.mgrid[0:SIZE, 0:SIZE][1] // 14).astype("uint8")             # three vertical stripes 0, 1, 2
    red = np.choose(truth, [0.1, 0.4, 0.7]) + rng.normal(0, 0.03, truth.shape)
    nir = np.choose(truth, [0.6, 0.2, 0.5]) + rng.normal(0, 0.03, truth.shape)
    image = _write(tmp_path / "present.tif", [red, nir], ["red", "nir"])
    labels = _write(tmp_path / "labels.tif", [truth], ["classes"], "uint8", 255)
    request = PredictionRequestDTO(CLASSIFY, [PredictionInputDTO(image, "2024-06-01")], label_path=labels,
                                   label_band="classes", algorithms=["logistic", "random_forest", "knn", "lda"],
                                   options=_options(importance=True))
    result = PredictionService().run(request)
    assert result.best.metrics["F1 (macro)"] > 0.95
    assert np.mean(result.best.prediction == truth) > 0.95
    assert result.best.importance and {n for n, _v in result.best.importance} == {"red", "nir"}


def test_anomalies_find_a_patch_that_suddenly_dropped(tmp_path):
    rng = np.random.default_rng(5)
    inputs = []
    for year, day in enumerate(DATES):
        values = 0.5 + rng.normal(0, 0.02, (SIZE, SIZE))
        if year == len(DATES) - 1:
            values[10:16, 10:16] = 0.05                                      # cleared in the present
        inputs.append(PredictionInputDTO(_write(tmp_path / f"v_{day}.tif", [values], ["NDVI"]), day))
    request = PredictionRequestDTO(ANOMALY, inputs, band="NDVI",
                                   algorithms=["zscore", "isolation_forest", "elliptic_envelope"],
                                   options=_options(contamination=0.03))
    result = PredictionService().run(request)
    flagged = result.best.prediction == 1
    assert flagged[10:16, 10:16].mean() > 0.9                                # the cleared patch is found
    assert result.scores[0].key == "ensemble"


def test_cancelling_stops_the_run(tmp_path):
    inputs, _ = _ndvi_series(tmp_path)
    progress = PredictionProgress()
    progress.cancel()
    with pytest.raises(PredictionError, match="cancelled"):
        PredictionService().run(PredictionRequestDTO(FORECAST, inputs, band="NDVI", target_date="2025-06-01",
                                                     algorithms=["linear"], options=_options()), progress)


def test_a_failing_algorithm_is_reported_and_the_rest_still_run(tmp_path, monkeypatch):
    inputs, _ = _ndvi_series(tmp_path)

    def broken(*_a):
        raise RuntimeError("boom")

    spec = algo.SPEC_BY_KEY["ridge"]
    monkeypatch.setitem(algo.SPEC_BY_KEY, "ridge", algo.Spec(**{**spec.__dict__, "build": broken}))
    result = PredictionService().run(PredictionRequestDTO(FORECAST, inputs, band="NDVI", target_date="2025-06-01",
                                                          algorithms=["ridge", "linear"], options=_options()))
    by_key = {s.key: s for s in result.scores}
    assert by_key["ridge"].error == "boom" and by_key["ridge"].rank == 0
    assert result.best.key == "linear"


def test_save_writes_the_prediction_with_its_layers(tmp_path):
    inputs, _ = _ndvi_series(tmp_path)
    service = PredictionService()
    result = service.run(PredictionRequestDTO(FORECAST, inputs, band="NDVI", target_date="2025-06-01",
                                              algorithms=["trend", "linear"], options=_options()))
    path = service.save(result, str(tmp_path / "out" / "forecast"))
    with rasterio.open(path) as src:
        assert path.endswith(".tif") and src.count >= 2 and src.crs.to_epsg() == 4326
        assert src.descriptions[0] == "NDVI on 2025-06-01"
        assert np.isfinite(src.read(1)).all()


def test_describe_guesses_the_date_and_class_bands(tmp_path):
    folder = tmp_path / "Sentinel-2_73.0000_31.0000_2023-01-01_2023-12-31"
    folder.mkdir()
    path = _write(folder / "image.tif", [np.random.rand(SIZE, SIZE), np.ones((SIZE, SIZE)) * 3], ["NDVI", "label"])
    info = PredictionService().describe(path)
    assert info.bands == ("NDVI", "label") and info.date == "2023-12-31" and info.categorical == ("label",)
