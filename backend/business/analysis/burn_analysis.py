"""Class diagram: BurnAnalysis. NBR, NBR2, BAI, CSI, and the before / after severity indices dNBR, RdNBR, RBR."""

from __future__ import annotations

from backend.business.analysis.base_analysis import BaseAnalysis


class BurnAnalysis(BaseAnalysis):
    CATEGORY = "Burn"
