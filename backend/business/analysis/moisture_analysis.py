"""Class diagram: MoistureAnalysis. NDMI, LSWI, NDII, MSI, NDDI and the condition indices VCI, TCI, VHI."""

from __future__ import annotations

from backend.business.analysis.base_analysis import BaseAnalysis


class MoistureAnalysis(BaseAnalysis):
    CATEGORY = "Moisture & drought"
