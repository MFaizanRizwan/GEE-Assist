"""Class diagram: UrbanAnalysis. NDBI, UI, IBI and BUI."""

from __future__ import annotations

from backend.business.analysis.base_analysis import BaseAnalysis


class UrbanAnalysis(BaseAnalysis):
    CATEGORY = "Built-up & urban"
