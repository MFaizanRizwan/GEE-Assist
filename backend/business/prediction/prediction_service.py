"""Machine-learning prediction from past and present GeoTIFFs (the Prediction page).

The user gives a series of dated GeoTIFFs of one place; the last is "the present". Every
chosen algorithm is trained, scored on data it did not see, and ranked; the best one's map
(and every other's) comes back with the scores.

How each task learns and is scored
----------------------------------
* forecast  – features: a pixel's last ``lags`` values, the days to the date predicted, the
  season (sine and cosine of the day of year) and its position. Target: the next value.
  Scored by predicting the present from the past (time hold-out); with too few dates for
  that, on a random fifth of the pixels (spatial hold-out). Then refitted on every date
  and run from the present to the target date.
* change    – features: the pixel's past classes, its present class (one-hot), the share of
  each class around it, the days ahead and its position. Target: the class at the next
  date. Scored and run as above.
* classify  – features: the present image's bands (optionally reduced by PCA). Labels: a
  class GeoTIFF or a shapefile of labelled points / areas. Scored on a stratified fifth of
  the labelled pixels (or by 5-fold cross-validation).
* anomaly   – features: the present value, its past mean, spread and trend, and how far the
  present is from them. Unsupervised: each detector is scored by how well it agrees with
  the consensus of all of them, and the consensus is offered as well.

Around the algorithms: feature scaling for the models that need it, optional PCA, optional
randomised hyperparameter search, an ensemble of the best three, permutation feature
importance and an uncertainty layer (how much the best models disagree).
"""

from __future__ import annotations

import math
import time
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from backend.business.prediction import algorithms as algo
from backend.business.prediction.i_prediction_service import IPredictionService
from backend.business.prediction.stack import (
    Grid,
    band_names,
    guess_date,
    looks_categorical,
    parse_date,
    read_band,
    read_bands,
    working_grid,
)
from backend.dto.prediction_dto import (
    ANOMALY,
    CHANGE,
    CLASSIFY,
    FORECAST,
    TASKS,
    AlgorithmDTO,
    ModelScoreDTO,
    PredictionProgress,
    PredictionRequestDTO,
    PredictionResultDTO,
    RasterBandsDTO,
)
from backend.exceptions import PredictionError

ENSEMBLE = "ensemble"
VALIDATION_ROWS = 20_000
IMPORTANCE_ROWS = 3_000
TUNE_ROWS = 5_000
GENERIC_COLOURS = ("#4E79A7", "#F28E2B", "#59A14F", "#E15759", "#76B7B2", "#EDC948", "#B07AA1", "#FF9DA7",
                   "#9C755F", "#BAB0AC", "#2F4B7C", "#A05195", "#D45087", "#665191", "#003F5C", "#FFA600")


class _Cancelled(Exception):
    pass


class PredictionService(IPredictionService):
    # ------------------------------------------------------------- what the page needs first
    def algorithms(self, task: str) -> list[AlgorithmDTO]:
        if task not in TASKS:
            raise PredictionError(f"Unknown task: {task!r}")
        return algo.algorithm_dtos(task)

    def describe(self, path: str) -> RasterBandsDTO:
        import rasterio
        from rasterio.enums import Resampling

        file = Path(path)
        if not file.is_file():
            raise PredictionError(f"The file is not there: {file}")
        if file.suffix.lower() == ".shp":
            return RasterBandsDTO(str(file), file.stem, ())
        try:
            with rasterio.open(str(file)) as src:
                names = band_names(src)
                tags = src.tags()
                sample = src.read(out_shape=(src.count, min(64, src.height), min(64, src.width)),
                                  resampling=Resampling.nearest, masked=True)
                width, height = src.width, src.height
        except rasterio.errors.RasterioIOError as exc:
            raise PredictionError(f"Cannot open {file.name}: {exc}") from exc
        categorical = tuple(name for name, band in zip(names, sample)
                            if looks_categorical(np.asarray(band.astype("float64").filled(np.nan))))
        return RasterBandsDTO(str(file), file.stem, names, guess_date(str(file), tags), width, height, categorical)

    # ------------------------------------------------------------- running
    def run(self, request: PredictionRequestDTO, progress: PredictionProgress | None = None) -> PredictionResultDTO:
        progress = progress or PredictionProgress()
        if request.task not in TASKS:
            raise PredictionError(f"Unknown task: {request.task!r}")
        keys = [k for k in dict.fromkeys(request.algorithms) if k in algo.SPEC_BY_KEY]
        allowed = {spec.key for spec in algo.specs_for(request.task)}
        keys = [k for k in keys if k in allowed]
        if not keys:
            raise PredictionError("Choose at least one algorithm.")
        inputs = sorted(request.inputs, key=lambda i: parse_date(i.date))
        minimum = {FORECAST: 2, CHANGE: 2, ANOMALY: 3, CLASSIFY: 1}[request.task]
        if len(inputs) < minimum:
            need = {FORECAST: "two dates (a past and the present)", CHANGE: "two class maps (a past and the present)",
                    ANOMALY: "three dates (two past and the present)", CLASSIFY: "the present image"}
            raise PredictionError(f"This needs at least {need[request.task]}.")
        if len({parse_date(i.date) for i in inputs}) != len(inputs):
            raise PredictionError("Two of the files have the same date; give each its own date.")
        try:
            runner = {FORECAST: self._forecast, CHANGE: self._change, CLASSIFY: self._classify,
                      ANOMALY: self._anomaly}[request.task]
            return runner(request, inputs, keys, progress)
        except _Cancelled:
            raise PredictionError("Prediction cancelled.") from None

    # ------------------------------------------------------------- forecast
    def _forecast(self, request, inputs, keys, progress) -> PredictionResultDTO:
        opts = request.options
        present_day = parse_date(inputs[-1].date)
        target_day = parse_date(request.target_date) if request.target_date else None
        if target_day is None or target_day <= present_day:
            raise PredictionError("Choose a target date after the present one "
                                  f"({present_day.isoformat()}).")
        if not request.band:
            raise PredictionError("Choose the band to forecast.")
        grid = working_grid(inputs[-1].path, opts.working_size)
        series = self._series(inputs, request.band, grid, False, progress)          # (T, H, W)
        days = np.array([parse_date(i.date).toordinal() for i in inputs], dtype="float64")
        lags = max(1, min(opts.lags, len(inputs) - 1))
        gx, gy = grid.coordinates()

        def features(k: int, ahead: float, doy_of: date) -> np.ndarray:
            """Rows for every pixel predicting date index k (or the target): (H*W, n)."""
            stack = series[k - lags:k].reshape(lags, -1).T                     # oldest first
            static = np.column_stack([
                np.full(stack.shape[0], ahead),
                np.full(stack.shape[0], math.sin(2 * math.pi * doy_of.timetuple().tm_yday / 365.25)),
                np.full(stack.shape[0], math.cos(2 * math.pi * doy_of.timetuple().tm_yday / 365.25)),
                gx.ravel(), gy.ravel()])
            return np.column_stack([stack, static])

        names = [f"value {lags - i} date(s) back" for i in range(lags)] + [
            "days ahead", "season (sin)", "season (cos)", "x (east)", "y (north)"]
        windows = list(range(lags, len(inputs)))
        rows_by_window = {k: (features(k, days[k] - days[k - 1], date.fromordinal(int(days[k]))),
                              series[k].ravel()) for k in windows}
        rng = np.random.default_rng(opts.seed)

        def usable(x, y):
            ok = np.isfinite(x).all(axis=1) & np.isfinite(y)
            return x[ok], y[ok]

        if len(windows) >= 2:   # time hold-out: learn from earlier dates, predict the present
            train_x, train_y = usable(np.vstack([rows_by_window[k][0] for k in windows[:-1]]),
                                      np.concatenate([rows_by_window[k][1] for k in windows[:-1]]))
            val_x, val_y = usable(*rows_by_window[windows[-1]])
            validation = (f"Trained on the dates before the present, scored on predicting the present "
                          f"({inputs[-1].date}).")
            val_k = windows[-1]
        else:                    # spatial hold-out on the one transition there is
            x, y = usable(*rows_by_window[windows[0]])
            order = rng.permutation(len(x))
            cut = len(x) // 5
            val_x, val_y, train_x, train_y = x[order[:cut]], y[order[:cut]], x[order[cut:]], y[order[cut:]]
            validation = ("Only one past-to-present step: scored on a random fifth of the pixels held out "
                          "(add more past dates for a time hold-out).")
            val_k = windows[0]
        if len(train_x) < 20 or len(val_x) < 5:
            raise PredictionError("Too few pixels have data on every date to learn from.")
        train_x, train_y = _sample(rng, opts.sample_size, train_x, train_y)
        val_x, val_y = _sample(rng, VALIDATION_ROWS, val_x, val_y)
        future_x = features(len(inputs), (target_day - present_day).days, target_day)
        all_x, all_y = usable(np.vstack([rows_by_window[k][0] for k in windows]),
                              np.concatenate([rows_by_window[k][1] for k in windows]))
        all_x, all_y = _sample(rng, opts.sample_size, all_x, all_y)
        valid_future = np.isfinite(future_x).all(axis=1)

        def baseline_future(key: str) -> np.ndarray:
            """A no-training baseline's map: the present itself, or each pixel's trend line."""
            if key == "persistence":
                return series[-1].ravel()
            return _trend(series, days, float(target_day.toordinal()))

        scores: list[ModelScoreDTO] = []
        fitted: dict[str, Any] = {}
        val_preds: dict[str, np.ndarray] = {}
        for n, key in enumerate(keys):
            _check(progress)
            spec = algo.SPEC_BY_KEY[key]
            progress.update(0.05 + 0.8 * n / len(keys), f"Training {spec.label} ({n + 1} of {len(keys)})…")
            started = time.perf_counter()
            score = ModelScoreDTO(key, spec.label)
            try:
                if key in algo.BASELINES:
                    future = baseline_future(key).astype("float64")
                    val_pred = self._baseline_on_val(key, series, days, val_k, rows_by_window, val_x)
                else:
                    model = self._fit(spec, algo.REGRESS, train_x, train_y, opts, lags, 0)
                    val_pred = model.predict(val_x)
                    final = self._fit(spec, algo.REGRESS, all_x, all_y, opts, lags, 0)
                    future = np.full(future_x.shape[0], np.nan)
                    future[valid_future] = _predict(final, future_x[valid_future])
                    fitted[key] = model
                score.metrics = _regression_metrics(val_y, val_pred)
                score.prediction = future.reshape(grid.height, grid.width).astype("float32")
                val_preds[key] = val_pred
            except _Cancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - one failing algorithm must not stop the others
                score.error = _short(exc)
            score.seconds = time.perf_counter() - started
            scores.append(score)

        ranked = _rank(scores, "RMSE", higher=False)
        top = [s for s in ranked if not s.error][:3]
        if request.options.ensemble and len(top) >= 2:
            ensemble = ModelScoreDTO(ENSEMBLE, f"Ensemble (mean of {', '.join(s.label for s in top)})")
            ensemble.metrics = _regression_metrics(val_y, np.mean([val_preds[s.key] for s in top], axis=0))
            ensemble.prediction = np.nanmean(np.stack([s.prediction for s in top]), axis=0).astype("float32")
            ranked = _rank(scores + [ensemble], "RMSE", higher=False)
        uncertainty = None
        if len(top) >= 2:
            with np.errstate(invalid="ignore"):
                uncertainty = np.nanstd(np.stack([s.prediction for s in top]), axis=0).astype("float32")
        self._importance(ranked, fitted, val_x, val_y, names, opts, progress, regression=True)
        progress.update(1.0, "Done.")
        notes = [f"{len(inputs)} dates, {lags} past value(s) per pixel, {len(train_x):,} training pixels."]
        return self._result(request, inputs, grid, ranked, "RMSE", False, series[-1], uncertainty, [], names,
                            validation, notes, target_day.isoformat())

    def _baseline_on_val(self, key, series, days, val_k, rows_by_window, val_x):
        """A baseline's predictions for exactly the validation rows."""
        x_all = rows_by_window[val_k][0]
        if key == "persistence":
            per_pixel = series[val_k - 1].ravel()
        else:
            per_pixel = _trend(series[:val_k], days[:val_k], days[val_k])
        lookup = _rows_of(x_all, val_x)
        return per_pixel[lookup]

    # ------------------------------------------------------------- future land cover / change
    def _change(self, request, inputs, keys, progress) -> PredictionResultDTO:
        opts = request.options
        present_day = parse_date(inputs[-1].date)
        target_day = parse_date(request.target_date) if request.target_date else None
        if target_day is None or target_day <= present_day:
            raise PredictionError(f"Choose a target date after the present one ({present_day.isoformat()}).")
        if not request.band:
            raise PredictionError("Choose the class band (land cover codes).")
        grid = working_grid(inputs[-1].path, opts.working_size)
        series = self._series(inputs, request.band, grid, True, progress)            # (T, H, W) codes
        finite = series[np.isfinite(series)]
        if finite.size == 0:
            raise PredictionError("The class band has no data.")
        codes = np.unique(np.round(finite)).astype(int)
        if codes.size > 40:
            raise PredictionError(f"{request.band} has {codes.size} distinct values: it does not look like "
                                  "class codes. Choose a land-cover band.")
        days = np.array([parse_date(i.date).toordinal() for i in inputs], dtype="float64")
        lags = max(1, min(opts.lags, len(inputs) - 1))
        gx, gy = grid.coordinates()
        radius = max(0, opts.neighbourhood)

        def features(k: int, ahead: float) -> np.ndarray:
            past = series[k - lags:k].reshape(lags, -1).T
            last = series[k - 1]
            onehot = np.stack([(last == c) for c in codes]).reshape(len(codes), -1).T.astype("float64")
            shares = _neighbour_shares(last, codes, radius).reshape(len(codes), -1).T
            static = np.column_stack([np.full(past.shape[0], ahead), gx.ravel(), gy.ravel()])
            out = np.column_stack([past, onehot, shares, static])
            out[~np.isfinite(last.ravel())] = np.nan
            return out

        names = ([f"class {lags - i} date(s) back" for i in range(lags)]
                 + [f"is {self._class_label(request.band, c)}" for c in codes]
                 + [f"share of {self._class_label(request.band, c)} around" for c in codes]
                 + ["days ahead", "x (east)", "y (north)"])
        windows = list(range(lags, len(inputs)))
        rows = {k: (features(k, days[k] - days[k - 1]), series[k].ravel()) for k in windows}
        rng = np.random.default_rng(opts.seed)

        def usable(x, y):
            ok = np.isfinite(x).all(axis=1) & np.isfinite(y)
            return x[ok], np.round(y[ok]).astype(int)

        if len(windows) >= 2:
            train_x, train_y = usable(np.vstack([rows[k][0] for k in windows[:-1]]),
                                      np.concatenate([rows[k][1] for k in windows[:-1]]))
            val_x, val_y = usable(*rows[windows[-1]])
            validation = f"Trained on earlier changes, scored on predicting the present classes ({inputs[-1].date})."
        else:
            x, y = usable(*rows[windows[0]])
            train_x, val_x, train_y, val_y = _stratified_split(rng, x, y)
            validation = ("Only one past-to-present change: scored on a stratified fifth of the pixels held out "
                          "(add more past dates for a time hold-out).")
        if len(train_x) < 20 or len(val_x) < 5:
            raise PredictionError("Too few pixels have classes on every date to learn from.")
        train_x, train_y = _balanced_sample(rng, opts.sample_size, train_x, train_y)
        val_x, val_y = _sample(rng, VALIDATION_ROWS, val_x, val_y)
        all_x, all_y = usable(np.vstack([rows[k][0] for k in windows]), np.concatenate([rows[k][1] for k in windows]))
        all_x, all_y = _balanced_sample(rng, opts.sample_size, all_x, all_y)
        future_x = features(len(inputs), (target_day - present_day).days)
        valid_future = np.isfinite(future_x).all(axis=1)
        present_codes = series[-1].ravel()
        last_lag = lags - 1   # column of the most recent class among the features

        scores, fitted, val_probas = self._classifiers(
            keys, train_x, train_y, val_x, val_y, all_x, all_y, future_x, valid_future, opts, lags, grid, progress,
            no_change=(val_x[:, last_lag], present_codes))
        ranked, uncertainty = self._finish_classifiers(scores, val_y, val_probas, opts)
        self._importance(ranked, fitted, val_x, val_y, names, opts, progress, regression=False)
        classes = [(int(c), self._class_label(request.band, c), self._class_colour(request.band, c, i))
                   for i, c in enumerate(codes)]
        notes = [f"{len(inputs)} class maps, {len(codes)} classes, {len(train_x):,} training pixels."]
        progress.update(1.0, "Done.")
        return self._result(request, inputs, grid, ranked, "F1 (macro)", True, series[-1], uncertainty, classes,
                            names, validation, notes, target_day.isoformat())

    # ------------------------------------------------------------- classify the present image
    def _classify(self, request, inputs, keys, progress) -> PredictionResultDTO:
        opts = request.options
        present = inputs[-1]
        grid = working_grid(present.path, opts.working_size)
        progress.update(0.02, f"Reading {Path(present.path).name}…")
        bands, names = read_bands(present.path, grid)                                  # (B, H, W)
        labels, label_names = self._labels(request, grid)
        x_all = bands.reshape(bands.shape[0], -1).T
        y_all = labels.ravel()
        ok = np.isfinite(x_all).all(axis=1) & np.isfinite(y_all)
        x, y = x_all[ok], np.round(y_all[ok]).astype(int)
        codes, counts = np.unique(y, return_counts=True)
        if codes.size < 2:
            raise PredictionError("The labels hold fewer than two classes over the image; two or more are needed.")
        if len(x) < 20:
            raise PredictionError("Too few labelled pixels fall on the image (fewer than 20).")
        rng = np.random.default_rng(opts.seed)
        x, y = _balanced_sample(rng, opts.sample_size, x, y)
        train_x, val_x, train_y, val_y = _stratified_split(rng, x, y)
        valid_future = np.isfinite(x_all).all(axis=1)
        validation = "Scored on a stratified fifth of the labelled pixels, held out from training."
        if opts.cross_validation:
            validation = "Scored by 5-fold stratified cross-validation over the labelled pixels (mean of the folds)."
        scores, fitted, val_probas = self._classifiers(
            keys, train_x, train_y, val_x, val_y, x, y, x_all, valid_future, opts, 0, grid, progress,
            cross_validate=(x, y) if opts.cross_validation else None)
        ranked, uncertainty = self._finish_classifiers(scores, val_y, val_probas, opts)
        self._importance(ranked, fitted, val_x, val_y, list(names), opts, progress, regression=False)
        classes = [(int(c), label_names.get(int(c), self._class_label(request.label_band, c)),
                    self._class_colour(request.label_band, c, i)) for i, c in enumerate(codes)]
        notes = [f"{len(names)} bands as features, {codes.size} classes, {int(ok.sum()):,} labelled pixels "
                 f"({', '.join(f'{label_names.get(int(c), c)}: {n:,}' for c, n in zip(codes, counts))})."]
        progress.update(1.0, "Done.")
        return self._result(request, inputs, grid, ranked, "F1 (macro)", True, None, uncertainty, classes,
                            list(names), validation, notes, present.date)

    def _labels(self, request, grid: Grid) -> tuple[np.ndarray, dict[int, str]]:
        if not request.label_path:
            raise PredictionError("Choose where the training labels come from (a class GeoTIFF or a shapefile).")
        path = Path(request.label_path)
        if path.suffix.lower() == ".shp":
            return self._rasterize_labels(str(path), request.label_field, grid)
        if not request.label_band:
            raise PredictionError("Choose the label band of the class GeoTIFF.")
        return read_band(str(path), request.label_band, grid, categorical=True), {}

    def _rasterize_labels(self, path: str, field: str, grid: Grid) -> tuple[np.ndarray, dict[int, str]]:
        from rasterio.features import rasterize
        from rasterio.warp import transform_geom

        from backend.business.vector import VectorService
        from backend.dto.vector_dto import MULTIPOINT, POINT, POLYGON

        if not field:
            raise PredictionError("Choose the shapefile's class field.")
        layer = VectorService().load_shapefile(path)
        values = [f.attributes.get(field) for f in layer.features]
        numeric = all(isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) == int(v)
                      for v in values if v is not None)
        if numeric:
            code_of = {v: int(v) for v in values if v is not None}
            names = {int(v): str(int(v)) for v in values if v is not None}
        else:
            text = sorted({str(v) for v in values if v not in (None, "")})
            code_of = {name: i + 1 for i, name in enumerate(text)}
            names = {i + 1: name for i, name in enumerate(text)}
            code_of = {v: code_of[str(v)] for v in values if v not in (None, "")}
        shapes = []
        for feature, value in zip(layer.features, values):
            if value in (None, "") or value not in code_of:
                continue
            if feature.kind in (POINT, MULTIPOINT):
                geometry = {"type": "MultiPoint", "coordinates": [list(p) for ring in feature.parts for p in ring]}
            elif feature.kind == POLYGON:
                geometry = {"type": "Polygon", "coordinates": [list(map(list, ring)) for ring in feature.parts]}
            else:
                geometry = {"type": "MultiLineString", "coordinates": [list(map(list, ring)) for ring in feature.parts]}
            shapes.append((transform_geom("EPSG:4326", grid.crs, geometry), code_of[value]))
        if not shapes:
            raise PredictionError(f"No feature of the shapefile has a value in {field!r}.")
        burnt = rasterize(shapes, out_shape=(grid.height, grid.width), transform=grid.transform, fill=-1,
                          all_touched=True, dtype="int32")
        labels = np.where(burnt >= 0, burnt, np.nan).astype("float64")
        return labels, names

    # ------------------------------------------------------------- anomalies
    def _anomaly(self, request, inputs, keys, progress) -> PredictionResultDTO:
        opts = request.options
        if not request.band:
            raise PredictionError("Choose the band to examine.")
        grid = working_grid(inputs[-1].path, opts.working_size)
        series = self._series(inputs, request.band, grid, False, progress)
        days = np.array([parse_date(i.date).toordinal() for i in inputs], dtype="float64")
        present, past = series[-1], series[:-1]
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = np.nanmean(past, axis=0)
            spread = np.nanstd(past, axis=0)
            z = (present - mean) / np.where(spread > 0, spread, np.nan)
            slope = _slope(past, days[:-1]) * 365.25
        z = np.where(np.isfinite(z), z, 0.0)
        names = ["present value", "past mean", "past spread", "present minus past mean", "z-score",
                 "present minus last past", "past trend per year"]
        feats = np.stack([present, mean, spread, present - mean, z, present - past[-1], slope]).reshape(7, -1).T
        valid = np.isfinite(feats).all(axis=1)
        if valid.sum() < 50:
            raise PredictionError("Too few pixels have data on every date.")
        rng = np.random.default_rng(opts.seed)
        sample, _ = _sample(rng, opts.sample_size, feats[valid], np.zeros(int(valid.sum())))
        contamination = min(0.4, max(0.001, opts.contamination))

        scores: list[ModelScoreDTO] = []
        raw: dict[str, np.ndarray] = {}
        for n, key in enumerate(keys):
            _check(progress)
            spec = algo.SPEC_BY_KEY[key]
            progress.update(0.1 + 0.75 * n / len(keys), f"Running {spec.label} ({n + 1} of {len(keys)})…")
            started = time.perf_counter()
            score = ModelScoreDTO(key, spec.label)
            try:
                if key == "zscore":
                    value = np.abs(z.ravel())
                else:
                    model = self._fit_outlier(spec, sample, opts)
                    value = np.full(feats.shape[0], np.nan)
                    value[valid] = -_score_samples(model, feats[valid])
                value = np.where(valid, value, np.nan)
                raw[key] = value
            except _Cancelled:
                raise
            except Exception as exc:  # noqa: BLE001
                score.error = _short(exc)
            score.seconds = time.perf_counter() - started
            scores.append(score)

        ranks = {key: _rank01(value) for key, value in raw.items()}
        threshold = 1.0 - contamination
        flags = {key: r >= threshold for key, r in ranks.items()}
        consensus = None
        if ranks:
            consensus = np.nanmean(np.stack(list(ranks.values())), axis=0)
            agreed = _rank01(consensus) >= threshold
        for score in scores:
            if score.error:
                continue
            flagged = flags[score.key] & valid
            score.metrics = {
                "Agreement (Jaccard)": _jaccard(flagged, agreed & valid),
                "Flagged %": 100.0 * flagged.sum() / max(1, valid.sum()),
                "Mean |z| flagged": float(np.mean(np.abs(z.ravel()[flagged]))) if flagged.any() else 0.0,
            }
            score.prediction = np.where(valid, flagged.astype("float32"), np.nan).reshape(grid.height, grid.width)
            score.confidence = ranks[score.key].reshape(grid.height, grid.width).astype("float32")
        ranked = _rank(scores, "Agreement (Jaccard)", higher=True)
        if opts.ensemble and len(ranks) >= 2:
            ensemble = ModelScoreDTO(ENSEMBLE, f"Consensus of {len(ranks)} detectors")
            flagged = agreed & valid
            ensemble.metrics = {"Agreement (Jaccard)": 1.0, "Flagged %": 100.0 * flagged.sum() / max(1, valid.sum()),
                                "Mean |z| flagged": float(np.mean(np.abs(z.ravel()[flagged]))) if flagged.any() else 0.0}
            ensemble.prediction = np.where(valid, flagged.astype("float32"), np.nan).reshape(grid.height, grid.width)
            ensemble.confidence = _rank01(consensus).reshape(grid.height, grid.width).astype("float32")
            ranked = [ensemble] + ranked
            for i, s in enumerate(r for r in ranked if not r.error):
                s.rank = i + 1
        validation = ("Unsupervised (there is no ground truth for anomalies): each detector is scored by its "
                      "agreement with the consensus of all of them; flagged = the top "
                      f"{contamination * 100:g}% most unusual pixels.")
        classes = [(0, "Usual", "#D9D9D9"), (1, "Anomaly", "#D7301F")]
        notes = [f"Present {inputs[-1].date} compared with {len(inputs) - 1} past dates."]
        progress.update(1.0, "Done.")
        return self._result(request, inputs, grid, ranked, "Agreement (Jaccard)", True, present, None, classes,
                            names, validation, notes, inputs[-1].date)

    # ------------------------------------------------------------- shared: classifiers
    def _classifiers(self, keys, train_x, train_y, val_x, val_y, all_x, all_y, future_x, valid_future, opts, lags,
                     grid, progress, no_change=None, cross_validate=None):
        scores, fitted, val_probas = [], {}, {}
        for n, key in enumerate(keys):
            _check(progress)
            spec = algo.SPEC_BY_KEY[key]
            progress.update(0.05 + 0.8 * n / len(keys), f"Training {spec.label} ({n + 1} of {len(keys)})…")
            started = time.perf_counter()
            score = ModelScoreDTO(key, spec.label)
            try:
                if key == "no_change":
                    if no_change is None:
                        raise PredictionError("Only for future land cover.")
                    val_pred = np.round(no_change[0]).astype(int)
                    future = no_change[1]
                    confidence = np.where(np.isfinite(future), 1.0, np.nan)
                else:
                    model = self._fit(spec, algo.CLASSIFIER, train_x, train_y, opts, lags, len(np.unique(train_y)))
                    val_pred = model.predict(val_x)
                    if hasattr(model, "predict_proba"):
                        val_probas[key] = (model.classes_ if hasattr(model, "classes_") else np.unique(train_y),
                                           model.predict_proba(val_x))
                    final = self._fit(spec, algo.CLASSIFIER, all_x, all_y, opts, lags, len(np.unique(all_y)))
                    future = np.full(future_x.shape[0], np.nan)
                    confidence = np.full(future_x.shape[0], np.nan)
                    chunk_pred, chunk_conf = _predict_classes(final, future_x[valid_future])
                    future[valid_future] = chunk_pred
                    confidence[valid_future] = chunk_conf
                    fitted[key] = model
                score.metrics = _classification_metrics(val_y, val_pred)
                if cross_validate is not None and key != "no_change":
                    score.metrics.update(self._cross_validate(spec, cross_validate, opts, lags))
                score.prediction = future.reshape(grid.height, grid.width).astype("float32")
                score.confidence = confidence.reshape(grid.height, grid.width).astype("float32")
                val_probas.setdefault(key, None)
            except _Cancelled:
                raise
            except Exception as exc:  # noqa: BLE001
                score.error = _short(exc)
            score.seconds = time.perf_counter() - started
            scores.append(score)
        return scores, fitted, val_probas

    def _finish_classifiers(self, scores, val_y, val_probas, opts):
        ranked = _rank(scores, "F1 (macro)", higher=True)
        top = [s for s in ranked if not s.error and val_probas.get(s.key) is not None][:3]
        if opts.ensemble and len(top) >= 2:
            classes = np.unique(np.concatenate([val_probas[s.key][0] for s in top]))
            total = np.zeros((len(val_y), len(classes)))
            for s in top:
                own, proba = val_probas[s.key]
                for j, c in enumerate(own):
                    total[:, np.searchsorted(classes, c)] += proba[:, j]
            ensemble = ModelScoreDTO(ENSEMBLE, f"Ensemble (soft vote of {', '.join(s.label for s in top)})")
            ensemble.metrics = _classification_metrics(val_y, classes[np.argmax(total, axis=1)])
            # the map: a majority vote of the three maps, confidence = their mean confidence
            maps = np.stack([s.prediction for s in top])
            ensemble.prediction = _majority(maps)
            ensemble.confidence = np.nanmean(np.stack([s.confidence for s in top]), axis=0).astype("float32")
            ranked = _rank(scores + [ensemble], "F1 (macro)", higher=True)
        uncertainty = None
        best = next((s for s in ranked if not s.error), None)
        if best is not None and best.confidence is not None:
            uncertainty = (1.0 - best.confidence).astype("float32")
        return ranked, uncertainty

    def _cross_validate(self, spec, data, opts, lags) -> dict[str, float]:
        from sklearn.model_selection import StratifiedKFold

        x, y = data
        folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=opts.seed)
        f1s, accuracies = [], []
        for train, test in folds.split(x, y):
            model = self._fit(spec, algo.CLASSIFIER, x[train], y[train], opts, lags, len(np.unique(y[train])))
            metrics = _classification_metrics(y[test], model.predict(x[test]))
            f1s.append(metrics["F1 (macro)"])
            accuracies.append(metrics["Accuracy"])
        return {"F1 (macro)": float(np.mean(f1s)), "F1 spread": float(np.std(f1s)),
                "Accuracy": float(np.mean(accuracies))}

    # ------------------------------------------------------------- shared: fitting
    def _fit(self, spec: algo.Spec, role: str, x, y, opts, sequence_length: int, n_classes: int):
        """Build, (optionally) tune and fit one algorithm on (x, y)."""
        if spec.build is None:
            raise PredictionError(f"{spec.label} cannot be trained.")
        if not algo.library_available(spec.library):
            raise PredictionError(f"{spec.label} needs {spec.library}, which is not installed.")
        rng = np.random.default_rng(opts.seed)
        if spec.max_train and len(x) > spec.max_train:
            if role == algo.CLASSIFIER:
                x, y = _balanced_sample(rng, spec.max_train, x, y)
            else:
                x, y = _sample(rng, spec.max_train, x, y)
        estimator = spec.build(role, n_classes, opts.seed)
        if hasattr(estimator, "sequence_length"):
            estimator.sequence_length = sequence_length
        model = self._pipeline(estimator, spec, opts, role)
        y_fit = y
        encoder = None
        if role == algo.CLASSIFIER and spec.library in ("xgboost",):
            encoder = np.unique(y)          # XGBoost wants classes 0..K-1
            y_fit = np.searchsorted(encoder, y)
        if opts.tune and spec.grid and len(np.unique(y_fit)) > 1:
            model = self._tune(model, spec, x, y_fit, opts, role)
        else:
            model.fit(x, y_fit)
        return _Decoded(model, encoder) if encoder is not None else model

    def _pipeline(self, estimator, spec: algo.Spec, opts, role: str):
        steps = []
        if spec.scale or (opts.pca and role == algo.CLASSIFIER):
            from sklearn.preprocessing import StandardScaler

            steps.append(("scale", StandardScaler()))
        if opts.pca and role == algo.CLASSIFIER and not hasattr(estimator, "sequence_length"):
            from sklearn.decomposition import PCA

            steps.append(("pca", PCA(n_components=0.95, random_state=opts.seed)))
        if not steps:
            return estimator
        from sklearn.pipeline import Pipeline

        return Pipeline(steps + [("model", estimator)])

    def _tune(self, model, spec: algo.Spec, x, y, opts, role: str):
        from sklearn.model_selection import RandomizedSearchCV

        rng = np.random.default_rng(opts.seed)
        tx, ty = _sample(rng, TUNE_ROWS, x, y)
        prefix = "model__" if hasattr(model, "steps") else ""
        space = {prefix + name: values for name, values in spec.grid.items()}
        combinations = int(np.prod([len(v) for v in space.values()]))
        search = RandomizedSearchCV(model, space, n_iter=min(8, combinations), cv=3, random_state=opts.seed,
                                    scoring="neg_root_mean_squared_error" if role == algo.REGRESS else "f1_macro",
                                    n_jobs=1, error_score="raise")
        search.fit(tx, ty)
        best = search.best_estimator_
        best.fit(x, y)
        return best

    def _fit_outlier(self, spec: algo.Spec, sample: np.ndarray, opts):
        if not algo.library_available(spec.library):
            raise PredictionError(f"{spec.label} needs {spec.library}, which is not installed.")
        rng = np.random.default_rng(opts.seed)
        if spec.max_train and len(sample) > spec.max_train:
            sample, _ = _sample(rng, spec.max_train, sample, np.zeros(len(sample)))
        estimator = spec.build(algo.OUTLIER, 0, opts.seed)
        if spec.key == "isolation_forest":
            estimator.set_params(contamination=min(0.4, max(0.001, opts.contamination)))
        model = self._pipeline(estimator, spec, opts, algo.OUTLIER)
        model.fit(sample)
        return model

    # ------------------------------------------------------------- shared: importance, series, result
    def _importance(self, ranked, fitted, val_x, val_y, names, opts, progress, regression: bool) -> None:
        if not opts.importance:
            return
        best = next((s for s in ranked if not s.error and s.key in fitted), None)
        if best is None:
            return
        from sklearn.inspection import permutation_importance

        progress.update(0.92, f"Measuring which features {best.label} relies on…")
        rng = np.random.default_rng(opts.seed)
        x, y = _sample(rng, IMPORTANCE_ROWS, val_x, val_y)
        try:
            result = permutation_importance(fitted[best.key], x, y, n_repeats=3, random_state=opts.seed,
                                            scoring="neg_root_mean_squared_error" if regression else "f1_macro")
        except Exception:  # noqa: BLE001 - importance is a bonus, never a failure
            return
        pairs = sorted(zip(names, result.importances_mean), key=lambda p: -p[1])
        best.importance = [(name, float(value)) for name, value in pairs]

    def _series(self, inputs, band: str, grid: Grid, categorical: bool, progress) -> np.ndarray:
        layers = []
        for n, item in enumerate(inputs):
            _check(progress)
            progress.update(0.04 * n / len(inputs), f"Reading {Path(item.path).name} ({item.date})…")
            layers.append(read_band(item.path, band, grid, categorical))
        series = np.stack(layers)
        if not np.isfinite(series).any(axis=0).any():
            raise PredictionError("The files have no data where they overlap the present image.")
        return series

    def _result(self, request, inputs, grid: Grid, ranked, metric, higher, present, uncertainty, classes, names,
                validation, notes, target_date) -> PredictionResultDTO:
        if not any(not s.error for s in ranked):
            reasons = "; ".join(f"{s.label}: {s.error}" for s in ranked[:4])
            raise PredictionError(f"Every chosen algorithm failed ({reasons}).")
        t = grid.transform
        notes = list(notes)
        if grid.scale > 1.01:
            notes.append(f"Computed at 1/{grid.scale:.1f} of the present image's resolution "
                         f"({grid.width} × {grid.height} cells).")
        return PredictionResultDTO(
            task=request.task, band=request.band, target_date=target_date, present_date=inputs[-1].date,
            scores=ranked, primary_metric=metric, higher_is_better=higher, width=grid.width, height=grid.height,
            bounds=grid.bounds_wgs84, crs=str(grid.crs), transform=(t.a, t.b, t.c, t.d, t.e, t.f),
            present=None if present is None else present.astype("float32"), uncertainty=uncertainty,
            classes=classes, feature_names=names, validation=validation, notes=notes, scale=grid.scale)

    @staticmethod
    def _class_label(band: str, code) -> str:
        from backend.business.map.colour_maps import CLASS_TABLES

        code = int(code)
        table = "dynamic_world" if (band or "").lower() in ("label", "dynamic_world", "lulc", "landcover") else None
        if (band or "").lower() in ("lc_type1", "modis_igbp"):
            table = "modis_igbp"
        if table:
            first, rows = CLASS_TABLES[table]
            if 0 <= code - first < len(rows):
                return rows[code - first][0]
        return f"Class {code}"

    @staticmethod
    def _class_colour(band: str, code, index: int) -> str:
        from backend.business.map.colour_maps import CLASS_TABLES

        code = int(code)
        table = "dynamic_world" if (band or "").lower() in ("label", "dynamic_world", "lulc", "landcover") else None
        if (band or "").lower() in ("lc_type1", "modis_igbp"):
            table = "modis_igbp"
        if table:
            first, rows = CLASS_TABLES[table]
            if 0 <= code - first < len(rows):
                return rows[code - first][1]
        return GENERIC_COLOURS[index % len(GENERIC_COLOURS)]

    # ------------------------------------------------------------- saving
    def save(self, result: PredictionResultDTO, path: str, key: str = "") -> str:
        import rasterio
        from rasterio.transform import Affine

        score = next((s for s in result.scores if s.key == key and not s.error), None) or result.best
        if score is None or score.prediction is None:
            raise PredictionError("There is no prediction to save.")
        target = Path(path)
        if target.suffix.lower() not in (".tif", ".tiff"):
            target = target.with_suffix(".tif")
        layers = [(score.prediction, {FORECAST: f"{result.band} on {result.target_date}",
                                      CHANGE: f"class on {result.target_date}", CLASSIFY: "class",
                                      ANOMALY: "anomaly (1) / usual (0)"}[result.task])]
        if score.confidence is not None:
            layers.append((score.confidence, "anomaly score 0-1" if result.task == ANOMALY else "confidence 0-1"))
        if result.uncertainty is not None and result.task == FORECAST:
            layers.append((result.uncertainty, "uncertainty (spread of the best models)"))
        if result.present is not None:
            layers.append((result.present, f"present ({result.present_date})"))
        nodata = -9999.0
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(str(target), "w", driver="GTiff", width=result.width, height=result.height,
                               count=len(layers), dtype="float32", crs=result.crs,
                               transform=Affine(*result.transform), nodata=nodata, compress="deflate") as dst:
                for index, (values, name) in enumerate(layers, start=1):
                    dst.write(np.where(np.isfinite(values), values, nodata).astype("float32"), index)
                    dst.set_band_description(index, name)
                dst.update_tags(model=score.label, task=result.task, target_date=result.target_date,
                                **{k: f"{v:.6g}" for k, v in score.metrics.items()})
        except (rasterio.errors.RasterioIOError, OSError) as exc:
            raise PredictionError(f"The prediction could not be written: {exc}") from exc
        return str(target)


# ------------------------------------------------------------- helpers
class _Decoded:
    """An estimator trained on class indices, answering in the original class codes."""

    def __init__(self, model, classes):
        self.model, self.classes_ = model, classes

    def predict(self, x):
        return self.classes_[np.asarray(self.model.predict(x)).astype(int)]

    def predict_proba(self, x):
        return self.model.predict_proba(x)

    def fit(self, x, y):
        self.model.fit(x, np.searchsorted(self.classes_, y))
        return self

    def get_params(self, deep=True):
        return {}


def _check(progress: PredictionProgress) -> None:
    if progress.cancelled:
        raise _Cancelled()


def _short(exc: Exception) -> str:
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    return text[:200]


def _sample(rng, count: int, x: np.ndarray, y: np.ndarray):
    if len(x) <= count:
        return x, y
    pick = rng.choice(len(x), count, replace=False)
    return x[pick], y[pick]


def _balanced_sample(rng, count: int, x: np.ndarray, y: np.ndarray):
    """Up to ``count`` rows, each class given an equal share (rare classes kept whole)."""
    if len(x) <= count:
        return x, y
    classes = np.unique(y)
    share = max(1, count // len(classes))
    picks = []
    for c in classes:
        members = np.nonzero(y == c)[0]
        picks.append(members if len(members) <= share else rng.choice(members, share, replace=False))
    pick = np.concatenate(picks)
    return x[pick], y[pick]


def _stratified_split(rng, x, y, held: float = 0.2):
    test = []
    for c in np.unique(y):
        members = rng.permutation(np.nonzero(y == c)[0])
        test.append(members[:max(1, int(len(members) * held))] if len(members) > 1 else members[:0])
    test = np.concatenate(test)
    mask = np.zeros(len(x), dtype=bool)
    mask[test] = True
    return x[~mask], x[mask], y[~mask], y[mask]


def _rows_of(all_rows: np.ndarray, chosen: np.ndarray) -> np.ndarray:
    """The pixel index of each chosen validation row, found by its exact features."""
    keys = {row.tobytes(): i for i, row in enumerate(all_rows)}
    return np.array([keys[row.tobytes()] for row in chosen])


def _predict(model, x: np.ndarray, chunk: int = 200_000) -> np.ndarray:
    return np.concatenate([np.asarray(model.predict(x[s:s + chunk]), dtype="float64")
                           for s in range(0, len(x), chunk)]) if len(x) else np.empty(0)


def _predict_classes(model, x: np.ndarray, chunk: int = 200_000):
    preds, confs = [], []
    for start in range(0, len(x), chunk):
        part = x[start:start + chunk]
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba(part)
            classes = getattr(model, "classes_", None)
            pred = np.asarray(classes)[np.argmax(proba, axis=1)] if classes is not None else model.predict(part)
            preds.append(pred.astype("float64"))
            confs.append(proba.max(axis=1))
        else:
            preds.append(np.asarray(model.predict(part), dtype="float64"))
            confs.append(np.full(len(part), np.nan))
    if not preds:
        return np.empty(0), np.empty(0)
    return np.concatenate(preds), np.concatenate(confs)


def _score_samples(model, x: np.ndarray, chunk: int = 200_000) -> np.ndarray:
    return np.concatenate([np.asarray(model.score_samples(x[s:s + chunk]), dtype="float64")
                           for s in range(0, len(x), chunk)])


def _regression_metrics(truth, pred) -> dict[str, float]:
    truth, pred = np.asarray(truth, dtype="float64"), np.asarray(pred, dtype="float64")
    ok = np.isfinite(truth) & np.isfinite(pred)
    truth, pred = truth[ok], pred[ok]
    if truth.size == 0:
        raise PredictionError("No validation pixel could be predicted.")
    error = pred - truth
    total = float(((truth - truth.mean()) ** 2).sum())
    return {"RMSE": float(np.sqrt(np.mean(error ** 2))), "MAE": float(np.mean(np.abs(error))),
            "R²": 1.0 - float((error ** 2).sum()) / total if total > 0 else 0.0, "Bias": float(error.mean())}


def _classification_metrics(truth, pred) -> dict[str, float]:
    truth, pred = np.asarray(truth).astype(int), np.asarray(pred).astype(int)
    classes = np.unique(np.concatenate([truth, pred]))
    f1s = []
    for c in np.unique(truth):
        tp = np.sum((pred == c) & (truth == c))
        fp = np.sum((pred == c) & (truth != c))
        fn = np.sum((pred != c) & (truth == c))
        f1s.append(2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 0.0)
    accuracy = float(np.mean(truth == pred))
    expected = sum(np.mean(truth == c) * np.mean(pred == c) for c in classes)
    kappa = (accuracy - expected) / (1 - expected) if expected < 1 else 1.0
    return {"F1 (macro)": float(np.mean(f1s)), "Accuracy": accuracy, "Kappa": float(kappa)}


def _rank(scores: list[ModelScoreDTO], metric: str, higher: bool) -> list[ModelScoreDTO]:
    ok = [s for s in scores if not s.error and metric in s.metrics and np.isfinite(s.metrics[metric])]
    failed = [s for s in scores if s not in ok]
    ok.sort(key=lambda s: -s.metrics[metric] if higher else s.metrics[metric])
    for i, s in enumerate(ok):
        s.rank = i + 1
    for s in failed:
        s.rank = 0
        if not s.error:
            s.error = "No score."
    return ok + failed


def _trend(series: np.ndarray, days: np.ndarray, at: float) -> np.ndarray:
    """Each pixel's least-squares line through its dates, read at day ``at`` (flattened)."""
    t, h, w = series.shape
    y = series.reshape(t, -1)
    if t == 1:
        return y[0]
    x = days - days.mean()
    ok = np.isfinite(y)
    n = ok.sum(axis=0)
    xm = np.where(ok, x[:, None], 0.0)
    ym = np.where(ok, y, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean_x = xm.sum(axis=0) / n
        mean_y = ym.sum(axis=0) / n
        cov = (np.where(ok, (x[:, None] - mean_x) * (y - mean_y), 0.0)).sum(axis=0)
        var = (np.where(ok, (x[:, None] - mean_x) ** 2, 0.0)).sum(axis=0)
        slope = np.where(var > 0, cov / var, 0.0)
        out = mean_y + slope * ((at - days.mean()) - mean_x)
    out[n == 0] = np.nan
    return out


def _slope(series: np.ndarray, days: np.ndarray) -> np.ndarray:
    """Each pixel's trend per day, (H, W)."""
    t, h, w = series.shape
    if t < 2:
        return np.zeros((h, w))
    future = _trend(series, days, days.mean() + 1.0)
    now = _trend(series, days, days.mean())
    return (future - now).reshape(h, w)


def _neighbour_shares(classes: np.ndarray, codes: np.ndarray, radius: int) -> np.ndarray:
    """The share of each class in the (2r+1)² window around every pixel: (K, H, W)."""
    if radius <= 0:
        return np.stack([(classes == c).astype("float64") for c in codes])
    size = 2 * radius + 1
    out = []
    valid = np.isfinite(classes).astype("float64")
    count = _box_sum(valid, size)
    for c in codes:
        hits = _box_sum((classes == c).astype("float64"), size)
        with np.errstate(invalid="ignore", divide="ignore"):
            out.append(np.where(count > 0, hits / count, np.nan))
    return np.stack(out)


def _box_sum(values: np.ndarray, size: int) -> np.ndarray:
    pad = size // 2
    padded = np.pad(values, pad)
    integral = np.pad(padded.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    h, w = values.shape
    return (integral[size:size + h, size:size + w] - integral[:h, size:size + w]
            - integral[size:size + h, :w] + integral[:h, :w])


def _rank01(values: np.ndarray) -> np.ndarray:
    """Each value's rank among the finite ones, 0 (lowest) to 1 (highest); NaN stays NaN."""
    out = np.full(values.shape, np.nan)
    ok = np.isfinite(values)
    if ok.sum() == 0:
        return out
    order = np.argsort(values[ok], kind="stable")
    ranks = np.empty(order.size)
    ranks[order] = np.arange(order.size)
    out[ok] = ranks / max(1, order.size - 1)
    return out


def _jaccard(a: np.ndarray, b: np.ndarray) -> float:
    union = np.sum(a | b)
    return float(np.sum(a & b) / union) if union else 1.0


def _majority(maps: np.ndarray) -> np.ndarray:
    """The class most of the (two or three) maps give each pixel; with no majority, the best
    model's (the first map's)."""
    first = maps[0].copy()
    if maps.shape[0] >= 3:
        second, third = maps[1], maps[2]
        outvoted = (second == third) & (first != second)   # the other two agree against the first
        first[outvoted] = second[outvoted]
    return first.astype("float32")
