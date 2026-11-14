"""Class diagram: LSTAnalysis. Land surface temperature maps and their change over time (FR-09).

The thermal band (Landsat ST_B10 / ST_B6, MODIS LST_Day_1km, ERA5-Land skin
temperature) is scaled to kelvin by ``sensors.scaling`` and shown in °C.

The temporal analysis takes two or more datasets of the same place: the change is
the latest minus the earliest; with dates for all of them, the trend is each pixel's
least-squares slope in °C per year.
"""

from __future__ import annotations

from datetime import date

from backend.business.analysis.base_analysis import BaseAnalysis
from backend.business.analysis.raster_engine import Accumulator, LayerSpec, Period

KELVIN = 273.15


def _years(period: Period) -> float | None:
    try:
        day = date.fromisoformat(period.date)
    except ValueError:
        return None
    return day.year + (day.timetuple().tm_yday - 1) / 365.25


def lst_celsius(block, period: int = -1):
    return block.roles(period)["thermal"] - block.xp.float32(KELVIN)


class PeriodMeans(Accumulator):
    """Average LST of each period."""

    def __init__(self, periods: list[Period]):
        self.periods = periods
        self.sums = [0.0] * len(periods)
        self.counts = [0] * len(periods)

    def add(self, block, outputs) -> None:
        for index in range(len(self.periods)):
            values = block.finite(lst_celsius(block, index))
            if values.size:
                self.sums[index] += block.backend.scalar(block.xp.sum(values.astype(block.xp.float64)))
                self.counts[index] += int(values.size)

    def metrics(self) -> dict[str, float]:
        return {f"Mean LST {period.label} (°C)": self.sums[i] / self.counts[i]
                for i, period in enumerate(self.periods) if self.counts[i]}


class LSTAnalysis(BaseAnalysis):
    CATEGORY = "Thermal"

    def _special_check(self, formula, period):
        if formula.key not in ("LSTMapping", "LSTTemporalAnalysis"):
            return ""
        return None if "thermal" in period.roles else "Needs a thermal or surface-temperature band (Landsat, " \
                                                       "MODIS LST or ERA5-Land)."

    def _special_layers(self, key, periods, params, notes):
        if key == "LSTMapping":
            return [LayerSpec("LST", "LST", lambda block: lst_celsius(block), "thermal", "°C")], [], []
        if key != "LSTTemporalAnalysis":
            return None
        layers = [LayerSpec("LST_change", "LST change", lambda block: lst_celsius(block, -1) - lst_celsius(block, 0),
                            "change", "°C", -5.0, 5.0)]
        years = [_years(period) for period in periods]
        if all(year is not None for year in years) and len(set(years)) > 1:
            layers.append(LayerSpec("LST_trend", "LST trend", lambda block: self._trend(block, years), "change",
                                    "°C/year", -1.0, 1.0))
        else:
            notes.append("No trend per year: the datasets' dates are unknown or the same.")
        return layers, [], [PeriodMeans(periods)]

    @staticmethod
    def _trend(block, years: list[float]):
        """Least-squares slope of LST against time, per pixel (NaN where any period has no data)."""
        xp = block.xp
        mean_t = sum(years) / len(years)
        weights = [t - mean_t for t in years]
        denominator = sum(w * w for w in weights)
        values = [lst_celsius(block, index) for index in range(len(years))]
        mean_v = sum(values) / len(values)
        return sum(xp.float32(w) * (v - mean_v) for w, v in zip(weights, values)) / xp.float32(denominator)
