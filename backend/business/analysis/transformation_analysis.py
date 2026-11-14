"""Tasseled Cap transformation and Principal Component Analysis.

Tasseled Cap uses published coefficients, so only Landsat 5/7 (Crist 1985) and Landsat
8/9 (Baig et al. 2014) are supported. PCA works on any dataset with two or more
data bands: a first pass adds up the band means and covariance, the second projects
every pixel onto the first three eigenvectors (largest variance first).
"""

from __future__ import annotations

import numpy as np

from backend.business.analysis.base_analysis import BaseAnalysis
from backend.business.analysis.index_math import TASSELED_CAP, TASSELED_CAP_ROLES, TASSELED_CAP_SENSOR
from backend.business.analysis.raster_engine import LayerSpec, Period, ScenePass
from backend.exceptions import AnalysisError

QA_BANDS = {"QA_PIXEL", "QA60", "SCL", "SummaryQA", "angle"}
MAX_COMPONENTS = 3


def pca_bands(period: Period) -> list[str]:
    return [name for name in period.band_names if name not in QA_BANDS]


class CovariancePass(ScenePass):
    """Band means and covariance over the pixels where every band has data."""

    name = "PCA"

    def __init__(self, bands: list[str]):
        self.bands = bands
        self.count = 0
        self.sums = np.zeros(len(bands))
        self.products = np.zeros((len(bands), len(bands)))

    def add(self, block) -> None:
        xp = block.xp
        stack = xp.stack([block.band(band).ravel() for band in self.bands], axis=1)
        stack = stack[xp.all(xp.isfinite(stack), axis=1)].astype(xp.float64)
        if not stack.shape[0]:
            return
        self.count += int(stack.shape[0])
        self.sums += block.backend.to_host(xp.sum(stack, axis=0))
        self.products += block.backend.to_host(stack.T @ stack)

    def result(self) -> dict:
        if self.count < 2:
            raise AnalysisError("PCA needs pixels where every band has data.")
        mean = self.sums / self.count
        covariance = self.products / self.count - np.outer(mean, mean)
        values, vectors = np.linalg.eigh(covariance)
        order = np.argsort(values)[::-1]
        values, vectors = np.clip(values[order], 0.0, None), vectors[:, order]
        total = values.sum() or 1.0
        return {"mean": mean, "vectors": vectors, "explained": values / total}


class TransformationAnalysis(BaseAnalysis):
    CATEGORY = "Transformations"

    def _special_check(self, formula, period: Period):
        if formula.key == "TasseledCap":
            if period.satellite not in TASSELED_CAP_SENSOR:
                return "Tasseled Cap coefficients are only built in for Landsat 5, 7, 8 and 9."
            missing = [role for role in TASSELED_CAP_ROLES if role not in period.roles]
            return f"Needs the {', '.join(missing)} bands." if missing else None
        if formula.key == "PCA":
            return None if len(pca_bands(period)) >= 2 else "Needs at least two data bands."
        return ""

    def _special_layers(self, key, periods, params, notes):
        period = periods[-1]
        if key == "TasseledCap":
            coefficients = TASSELED_CAP[TASSELED_CAP_SENSOR[period.satellite]]

            def component(weights):
                def compute(block):
                    b = block.roles()
                    return sum(block.xp.float32(w) * b[role] for w, role in zip(weights, TASSELED_CAP_ROLES))
                return compute

            styles = {"brightness": "grey", "greenness": "vegetation", "wetness": "water"}
            layers = [LayerSpec(f"TC_{name}", f"TC {name}", component(weights), styles[name])
                      for name, weights in coefficients.items()]
            return layers, [], []
        if key == "PCA":
            bands = pca_bands(period)
            count = min(MAX_COMPONENTS, len(bands))
            layers = [LayerSpec(f"PC{i + 1}", f"PC{i + 1}", self._projection(bands, i), "viridis")
                      for i in range(count)]
            return layers, [CovariancePass(bands)], [_Explained(count)]
        return None

    @staticmethod
    def _projection(bands: list[str], component: int):
        def compute(block):
            xp = block.xp
            pca = block.scene["PCA"]
            weights = pca["vectors"][:, component]
            return sum(xp.float32(w) * (block.band(band) - xp.float32(m))
                       for w, m, band in zip(weights, pca["mean"], bands))
        return compute


class _Explained:
    """Adds each component's share of the variance to the metrics (read from the scene)."""

    def __init__(self, count: int):
        self.count = count
        self.explained = None

    def add(self, block, outputs) -> None:
        self.explained = block.scene["PCA"]["explained"]

    def metrics(self) -> dict[str, float]:
        if self.explained is None:
            return {}
        return {f"PC{i + 1} variance explained (%)": float(100.0 * self.explained[i]) for i in range(self.count)}
