"""A curated country list for per-country providers (DIVA-GIS uses ISO3, GeoNames uses ISO2)."""

from __future__ import annotations

# (name, ISO2, ISO3), alphabetical. A broad but manageable set across the continents.
COUNTRIES: tuple[tuple[str, str, str], ...] = (
    ("Afghanistan", "AF", "AFG"), ("Algeria", "DZ", "DZA"), ("Argentina", "AR", "ARG"),
    ("Australia", "AU", "AUS"), ("Bangladesh", "BD", "BGD"), ("Brazil", "BR", "BRA"),
    ("Canada", "CA", "CAN"), ("Chile", "CL", "CHL"), ("China", "CN", "CHN"),
    ("Colombia", "CO", "COL"), ("Egypt", "EG", "EGY"), ("Ethiopia", "ET", "ETH"),
    ("France", "FR", "FRA"), ("Germany", "DE", "DEU"), ("Ghana", "GH", "GHA"),
    ("Greece", "GR", "GRC"), ("India", "IN", "IND"), ("Indonesia", "ID", "IDN"),
    ("Iran", "IR", "IRN"), ("Iraq", "IQ", "IRQ"), ("Italy", "IT", "ITA"),
    ("Japan", "JP", "JPN"), ("Kenya", "KE", "KEN"), ("Malaysia", "MY", "MYS"),
    ("Mexico", "MX", "MEX"), ("Morocco", "MA", "MAR"), ("Nepal", "NP", "NPL"),
    ("Nigeria", "NG", "NGA"), ("Pakistan", "PK", "PAK"), ("Peru", "PE", "PER"),
    ("Philippines", "PH", "PHL"), ("Poland", "PL", "POL"), ("Russia", "RU", "RUS"),
    ("Saudi Arabia", "SA", "SAU"), ("South Africa", "ZA", "ZAF"), ("Spain", "ES", "ESP"),
    ("Sri Lanka", "LK", "LKA"), ("Sudan", "SD", "SDN"), ("Sweden", "SE", "SWE"),
    ("Tanzania", "TZ", "TZA"), ("Thailand", "TH", "THA"), ("Turkey", "TR", "TUR"),
    ("Uganda", "UG", "UGA"), ("Ukraine", "UA", "UKR"), ("United Kingdom", "GB", "GBR"),
    ("United States", "US", "USA"), ("Vietnam", "VN", "VNM"), ("Zambia", "ZM", "ZMB"),
    ("Zimbabwe", "ZW", "ZWE"),
)


def options(code: str):
    """``CatalogOptionDTO`` list keyed by ISO2 ("iso2") or ISO3 ("iso3"), labelled by name."""
    from backend.dto.catalog_dto import CatalogOptionDTO

    index = 1 if code == "iso2" else 2
    return tuple(CatalogOptionDTO(row[index], row[0]) for row in COUNTRIES)
