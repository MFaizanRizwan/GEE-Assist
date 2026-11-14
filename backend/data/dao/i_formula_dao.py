from __future__ import annotations

from abc import ABC, abstractmethod

from backend.dto.analysis_dto import FormulaDTO


class IFormulaDAO(ABC):
    """Class diagram: IFormulaDAO. The spectral indices and methods GEE-Assist knows."""

    @abstractmethod
    def find_all(self) -> list[FormulaDTO]:
        """Every formula, in category order (see ``categories``)."""

    @abstractmethod
    def find_by_key(self, key: str) -> FormulaDTO | None:
        """The formula with this key or alias (case-insensitive), or None."""

    @abstractmethod
    def find_by_category(self, category: str) -> list[FormulaDTO]: ...

    @abstractmethod
    def categories(self) -> list[tuple[str, str]]:
        """(category, what it is for), in display order."""
