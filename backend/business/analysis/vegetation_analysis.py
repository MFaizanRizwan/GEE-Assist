"""Class diagram: VegetationAnalysis. NDVI, EVI, SAVI, MSAVI, GNDVI, red-edge and chlorophyll indices, LAI, FAPAR, FCover."""

from __future__ import annotations

from backend.business.analysis.base_analysis import BaseAnalysis


class VegetationAnalysis(BaseAnalysis):
    CATEGORY = "Vegetation"
