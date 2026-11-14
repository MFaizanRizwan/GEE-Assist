"""Class diagram: VegetationAnalysis (FR-07). Sub-types: vegetation indices (NDVI, EVI, SAVI, red-edge and
chlorophyll indices, LAI, FAPAR, FCover), moisture & drought (NDMI, MSI, NDDI, VCI, ...) and burn & fire
(NBR, dNBR, RdNBR, RBR, BAI, ...). All are formulas, so no code beyond the base class is needed.
"""

from __future__ import annotations

from backend.business.analysis.base_analysis import BaseAnalysis


class VegetationAnalysis(BaseAnalysis):
    CATEGORY = "Vegetation"
