"""Class diagram: SoilAnalysis. Bare soil, salinity, brightness, clay, iron oxide and crop residue indices."""

from __future__ import annotations

from backend.business.analysis.base_analysis import BaseAnalysis


class SoilAnalysis(BaseAnalysis):
    CATEGORY = "Soil & salinity"
