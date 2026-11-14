"""Class diagram: SnowAnalysis. NDSI, NDGI and S3."""

from __future__ import annotations

from backend.business.analysis.base_analysis import BaseAnalysis


class SnowAnalysis(BaseAnalysis):
    CATEGORY = "Snow & ice"
