"""The prompt that asks Gemini to explain an analysis result."""

from backend.data.clients.prompts import EXPLANATION_SYSTEM_PROMPT, build_explanation_prompt
from backend.dto.explanation_dto import (
    ExplanationRequestDTO,
    LayerInfoDTO,
    ProcessInfoDTO,
    RasterMetadataDTO,
)
from backend.dto.result_dto import ResultDTO

BEFORE = RasterMetadataDTO("Sentinel-2_73.07_31.43_2024-06-01_2024-06-30", "C:/p/downloads/a.tif",
                           satellite="Sentinel-2", start_date="2024-06-01", end_date="2024-06-30",
                           bands=("B4", "B8"), width=400, height=300, crs="EPSG:4326",
                           bounds=(73.0, 31.4, 73.1, 31.5), area_km2=104.2)
EARLIER = RasterMetadataDTO("Sentinel-2_73.07_31.43_2023-06-01_2023-06-30", "C:/p/downloads/b.tif",
                            start_date="2023-06-01", end_date="2023-06-30")
AFTER = RasterMetadataDTO("result", "C:/p/analysis/result.tif", bands=("NDVI", "dNBR"), width=400, height=300,
                          nodata=-9999.0)


def request(**changes) -> ExplanationRequestDTO:
    values = dict(
        result=ResultDTO("r1", "Vegetation", ["NDVI", "dNBR"], {"NDVI mean": 0.42, "Burned area (km²)": 3.5},
                         "C:/p/analysis/result.tif", "2024-07-01T10:00:00", device="CPU", seconds=2.5,
                         notes=["Clouds were masked."], saved=True),
        category="Vegetation", category_label="Vegetation",
        processes=(ProcessInfoDTO("NDVI", "Normalized Difference Vegetation Index", "(NIR − Red) / (NIR + Red)",
                                  "−1 to 1", "Higher is greener."), ProcessInfoDTO("dNBR")),
        params={"savi_l": 0.5}, before=BEFORE, compared_with=(EARLIER,), after=AFTER,
        layers=(LayerInfoDTO("NDVI", "NDVI", legend="red to green over -0.2 to 0.8"),
                LayerInfoDTO("dNBR", "dNBR")),
        previews=(b"png1", b"png2"),
    )
    values.update(changes)
    return ExplanationRequestDTO(**values)


def test_the_prompt_names_the_analysis_its_processes_and_settings():
    prompt = build_explanation_prompt(request())
    assert "- Analysis: Vegetation" in prompt
    assert "  - NDVI: Normalized Difference Vegetation Index; formula (NIR − Red) / (NIR + Red)" in prompt
    assert "  - dNBR" in prompt
    assert "- Parameters: savi_l = 0.5" in prompt
    assert "- Ran on CPU in 2.5 s at 2024-07-01T10:00:00" in prompt


def test_the_prompt_gives_the_metadata_before_and_after_the_analysis():
    prompt = build_explanation_prompt(request())
    before = prompt.index("# Metadata before the analysis (the dataset analysed)")
    compared = prompt.index("compared dataset 1 (earlier date)")
    after = prompt.index("# Metadata after the analysis (the result GeoTIFF)")
    assert before < compared < after
    assert "- Satellite: Sentinel-2" in prompt[before:compared]
    assert "- Dates: 2023-06-01 to 2023-06-30" in prompt[compared:after]
    assert "- Bands (2): NDVI, dNBR" in prompt[after:]
    assert "  1. NDVI (NDVI): preview coloured red to green over -0.2 to 0.8" in prompt


def test_the_prompt_lists_the_numbers_notes_and_attachments():
    prompt = build_explanation_prompt(request())
    assert "- NDVI mean: 0.42" in prompt and "- Burned area (km²): 3.5" in prompt
    assert "- Clouds were masked." in prompt
    assert "- The result GeoTIFF result.tif" in prompt
    assert "2 PNG preview(s), one per layer, in this order: NDVI, dNBR" in prompt


def test_missing_metadata_is_said_rather_than_invented():
    prompt = build_explanation_prompt(request(before=None, after=None, compared_with=(), previews=()))
    assert prompt.count("- Not available") == 2
    assert "PNG preview" not in prompt


def test_the_system_prompt_forbids_invented_values():
    assert "never invent values" in EXPLANATION_SYSTEM_PROMPT
