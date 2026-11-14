"""Class diagram: FormulaDAO. Serves the formula catalogue (read-only, built into the app)."""

from __future__ import annotations

from backend.data.dao.formula_catalogue import CATEGORY_DESCRIPTIONS, CATEGORY_ORDER, FORMULAS
from backend.data.dao.i_formula_dao import IFormulaDAO
from backend.dto.analysis_dto import FormulaDTO


class FormulaDAO(IFormulaDAO):
    def __init__(self, formulas: tuple[FormulaDTO, ...] = FORMULAS):
        order = {category: index for index, category in enumerate(CATEGORY_ORDER)}
        # Stable sort: within a category the catalogue's order is kept.
        self._formulas = sorted(formulas, key=lambda f: order.get(f.category, len(order)))
        self._by_name: dict[str, FormulaDTO] = {}
        for formula in self._formulas:
            for name in (formula.key, *formula.aliases):
                self._by_name.setdefault(name.lower(), formula)

    def find_all(self) -> list[FormulaDTO]:
        return list(self._formulas)

    def find_by_key(self, key: str) -> FormulaDTO | None:
        return self._by_name.get(key.lower())

    def find_by_category(self, category: str) -> list[FormulaDTO]:
        return [formula for formula in self._formulas if formula.category == category]

    def categories(self) -> list[tuple[str, str]]:
        present = {formula.category for formula in self._formulas}
        return [(category, CATEGORY_DESCRIPTIONS.get(category, "")) for category in CATEGORY_ORDER
                if category in present]
