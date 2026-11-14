"""Analyses (UC-06): formulas, index arithmetic, sensor scaling, GPU choice and full runs on small GeoTIFFs."""

from __future__ import annotations

import json
import types
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin  # noqa: E402

from backend.business.analysis import AnalysisService  # noqa: E402
from backend.business.analysis.compute_device import (  # noqa: E402
    CUPY_HINT,
    ComputeBackend,
    classify,
    cpu_backend,
    detect_gpus,
    select_backend,
)
from backend.business.analysis.index_math import INDEX_FUNCTIONS  # noqa: E402
from backend.business.analysis.sensors import NODATA, resolve_satellite, scaling  # noqa: E402
from backend.business.facade import BusinessFacade  # noqa: E402
from backend.business.map import MapService  # noqa: E402
from backend.data.dao.formula_catalogue import ANALYSIS_ORDER, CATEGORY_ORDER, FORMULAS, SUBTYPES  # noqa: E402
from backend.data.dao.formula_dao import FormulaDAO  # noqa: E402
from backend.data.data_facade import DataFacade  # noqa: E402
from backend.dto.analysis_dto import GPU_DEDICATED, GPU_INTEGRATED, GPU_VIRTUAL, AnalysisRequestDTO, GpuDTO  # noqa: E402
from backend.dto.download_dto import JOB_COMPLETED, JOB_FAILED, DatasetDTO, DownloadJobDTO  # noqa: E402
from backend.dto.project_dto import ProjectDTO  # noqa: E402
from backend.exceptions import AnalysisError  # noqa: E402

S2_BANDS = ("B2", "B3", "B4", "B5", "B6", "B8", "B11", "B12")
SPECIAL = {"WaterBodyDetection", "WaterAreaEstimation", "LSTMapping", "LSTTemporalAnalysis", "LULCChangeDetection",
           "LULCTransition", "TasseledCap", "PCA"}
NO_GPU = (GpuDTO("AMD Radeon (TM) Graphics", "AMD", GPU_INTEGRATED),)


def write_tif(path, bands: dict[str, np.ndarray], crs="EPSG:4326", pixel=0.0001):
    height, width = next(iter(bands.values())).shape
    with rasterio.open(path, "w", driver="GTiff", width=width, height=height, count=len(bands), dtype="float32",
                       crs=crs, transform=from_origin(73.0, 31.5, pixel, pixel), nodata=NODATA) as dst:
        for index, (name, data) in enumerate(bands.items(), start=1):
            dst.write(data.astype("float32"), index)
            dst.set_band_description(index, name)
    return str(path)


def s2_file(tmp_path, name="Sentinel-2_73.0150_31.4900_2024-06-01_2024-06-30.tif", seed=0, shape=(40, 60)):
    rng = np.random.default_rng(seed)
    bands = {band: rng.uniform(300, 4000, shape) for band in S2_BANDS}
    bands["B3"][:10] = 3000   # top rows: water (bright green, dark NIR and SWIR)
    bands["B8"][:10] = 200
    bands["B11"][:10] = 150
    bands["B4"][0, 0] = NODATA
    return write_tif(tmp_path / name, bands)


@pytest.fixture
def service():
    return AnalysisService(DataFacade(gemini_client=None), find_gpus=lambda: NO_GPU, block_rows=16)


def read(path, band):
    with rasterio.open(path) as src:
        return src.read(list(src.descriptions).index(band) + 1)


# ------------------------------------------------------------------ formula table
def test_formula_keys_are_unique_and_every_category_is_known():
    keys = [formula.key for formula in FORMULAS]
    assert len(keys) == len(set(keys))
    assert {formula.category for formula in FORMULAS} == set(CATEGORY_ORDER)
    assert all(formula.formula and formula.use_cases for formula in FORMULAS)


def test_formulas_are_sub_types_of_the_four_analyses():
    assert ANALYSIS_ORDER == ("Water", "Vegetation", "LST", "LULC")
    for formula in FORMULAS:
        assert formula.category in SUBTYPES[formula.analysis], formula.key
    groups = FormulaDAO().analyses()
    assert [group[0] for group in groups] == list(ANALYSIS_ORDER)
    assert groups[1][3] == ("Vegetation indices", "Moisture & drought", "Burn & fire")
    assert FormulaDAO().find_by_key("dNBR").analysis == "Vegetation"
    assert FormulaDAO().find_by_key("PCA").analysis == "LULC"


def test_every_computable_formula_has_arithmetic():
    for formula in FORMULAS:
        if formula.computable:
            assert formula.key in INDEX_FUNCTIONS or formula.key in SPECIAL, formula.key
            if formula.key in INDEX_FUNCTIONS:
                assert set(INDEX_FUNCTIONS[formula.key].roles) == set(formula.bands), formula.key
        else:
            assert formula.note, f"{formula.key} should say why it is not computed"


def test_dao_finds_aliases_and_keeps_category_order():
    dao = FormulaDAO()
    assert dao.find_by_key("cigreen").key == "GCI"
    assert dao.find_by_key("CIred-edge").key == "CIre"
    assert [category for category, _ in dao.categories()] == list(CATEGORY_ORDER)
    order = [CATEGORY_ORDER.index(formula.category) for formula in dao.find_all()]
    assert order == sorted(order)


# ------------------------------------------------------------------ arithmetic and scaling
def test_index_values():
    b = {"nir": np.float32(0.5), "red": np.float32(0.1), "blue": np.float32(0.05), "green": np.float32(0.08),
         "swir1": np.float32(0.2)}
    assert INDEX_FUNCTIONS["NDVI"].fn(np, b, {}) == pytest.approx(0.4 / 0.6)
    assert INDEX_FUNCTIONS["EVI"].fn(np, b, {}) == pytest.approx(2.5 * 0.4 / (0.5 + 0.6 - 0.375 + 1))
    assert INDEX_FUNCTIONS["SAVI"].fn(np, b, {"savi_l": 0.5}) == pytest.approx(1.5 * 0.4 / 1.1)
    assert INDEX_FUNCTIONS["MNDWI"].fn(np, b, {}) == pytest.approx((0.08 - 0.2) / 0.28)
    before = {"nir": np.float32(0.5), "swir2": np.float32(0.1)}
    after = {"nir": np.float32(0.2), "swir2": np.float32(0.3)}
    assert INDEX_FUNCTIONS["dNBR"].fn(np, after, {"before": before}) == pytest.approx(0.4 / 0.6 + 0.2)


def test_scaling_turns_raw_values_into_reflectance_and_kelvin():
    assert scaling("Sentinel-2", "B8") == (0.0001, 0.0)
    assert scaling("Landsat-8", "SR_B5") == (0.0000275, -0.2)
    assert scaling("Landsat-8", "ST_B10") == (0.00341802, 149.0)
    assert scaling("MODIS-Terra", "LST_Day_1km") == (0.02, 0.0)
    assert scaling("Sentinel-1", "VV") == (1.0, 0.0)


def test_satellite_from_collection_name_or_bands():
    assert resolve_satellite(DatasetDTO("1", "LANDSAT/LC09/C02/T1_L2", "x.tif")) == "Landsat-9"
    assert resolve_satellite(DatasetDTO("", "", "Sentinel-1_1_2.tif")) == "Sentinel-1"
    assert resolve_satellite(DatasetDTO("", "", "mine.tif"), ("B2", "B3", "B4", "B8")) == "Sentinel-2"
    assert resolve_satellite(DatasetDTO("", "", "mine.tif"), ("label",)) == "Dynamic-World"


# ------------------------------------------------------------------ GPUs
@pytest.mark.parametrize("name, kind", [
    ("NVIDIA GeForce RTX 3060 Laptop GPU", GPU_DEDICATED),
    ("AMD Radeon RX 6700 XT", GPU_DEDICATED),
    ("AMD Radeon (TM) Graphics", GPU_INTEGRATED),
    ("AMD Radeon(TM) Vega 8 Graphics", GPU_INTEGRATED),
    ("AMD Radeon 780M", GPU_INTEGRATED),
    ("Intel(R) UHD Graphics 620", GPU_INTEGRATED),
    ("Intel(R) Arc(TM) A770 Graphics", GPU_DEDICATED),
    ("Microsoft Basic Display Adapter", GPU_VIRTUAL),
])
def test_graphics_cards_are_classed_by_name(name, kind):
    assert classify(name).kind == kind


def test_detection_reads_wmi_and_nvidia_smi():
    outputs = {
        "powershell": json.dumps([{"Name": "Intel(R) UHD Graphics 630", "AdapterRAM": 1073741824},
                                  {"Name": "NVIDIA GeForce RTX 4070", "AdapterCompatibility": "NVIDIA",
                                   "AdapterRAM": 4293918720}]),
        "nvidia-smi": "NVIDIA GeForce RTX 4070, 12282\n",
    }
    gpus = detect_gpus(run=lambda command: outputs.get(command[0], ""), platform="win32")
    assert [gpu.name for gpu in gpus] == ["NVIDIA GeForce RTX 4070", "Intel(R) UHD Graphics 630"]
    assert gpus[0].memory_bytes == 12282 * 1024 * 1024  # nvidia-smi's exact size, not WMI's 4 GB cap


def test_detection_of_a_single_card_and_of_nothing():
    one = json.dumps({"Name": "AMD Radeon (TM) Graphics", "AdapterRAM": 536870912})
    assert [g.kind for g in detect_gpus(run=lambda c: one if c[0] == "powershell" else "", platform="win32")] == \
        [GPU_INTEGRATED]
    assert detect_gpus(run=lambda c: "", platform="win32") == []


def test_cpu_without_a_dedicated_gpu():
    backend = select_backend(NO_GPU)
    assert backend.xp is np and not backend.uses_gpu and "No dedicated GPU" in backend.device.reason


def test_amd_dedicated_gpu_falls_back_to_cpu_with_reason():
    backend = select_backend([classify("AMD Radeon RX 7900 XT")])
    assert not backend.uses_gpu and "NVIDIA" in backend.device.reason


def test_nvidia_without_cupy_says_how_to_install_it():
    def missing():
        raise ImportError("no cupy")

    backend = select_backend([classify("NVIDIA GeForce RTX 3060")], load_cupy=missing)
    assert not backend.uses_gpu and CUPY_HINT in backend.device.reason


def test_nvidia_with_a_broken_cuda_uses_the_cpu():
    def broken():
        raise RuntimeError("CUDA driver version is insufficient")

    backend = select_backend([classify("NVIDIA GeForce RTX 3060")], load_cupy=broken)
    assert not backend.uses_gpu and "CUDA did not start" in backend.device.reason


def test_gpu_can_be_turned_off():
    backend = select_backend([classify("NVIDIA GeForce RTX 3060")], use_gpu=False, load_cupy=lambda: FAKE_CUPY)
    assert not backend.uses_gpu


class _FakeCupy(types.ModuleType):
    """Stands in for CuPy: NumPy underneath, but only reachable through CuPy's API (asnumpy, memory pool)."""

    def __init__(self):
        super().__init__("cupy")
        self.transfers = 0
        self.cuda = types.SimpleNamespace(runtime=types.SimpleNamespace(getDeviceCount=lambda: 1))

    def __getattr__(self, name):
        return getattr(np, name)

    def asnumpy(self, array):
        self.transfers += 1
        return np.asarray(array)

    def get_default_memory_pool(self):
        return types.SimpleNamespace(free_all_blocks=lambda: None)


FAKE_CUPY = _FakeCupy()


def test_analysis_on_the_gpu_gives_the_cpu_result(tmp_path):
    path = s2_file(tmp_path)
    gpu = [classify("NVIDIA GeForce RTX 3060")]
    on_gpu = AnalysisService(DataFacade(gemini_client=None), find_gpus=lambda: gpu, block_rows=16,
                             select=lambda gpus, use: select_backend(gpus, use, load_cupy=lambda: FAKE_CUPY))
    on_cpu = AnalysisService(DataFacade(gemini_client=None), find_gpus=lambda: NO_GPU, block_rows=16)
    dataset = on_gpu.describe_dataset(path)
    assert on_gpu.get_compute_device().uses_gpu
    request = dict(category="Vegetation", processes=["NDVI", "EVI"])
    gpu_result = on_gpu.run_analysis(dataset, AnalysisRequestDTO(**request, output_dir=str(tmp_path / "gpu")))
    cpu_result = on_cpu.run_analysis(dataset, AnalysisRequestDTO(**request, output_dir=str(tmp_path / "cpu")))
    assert gpu_result.device == "GPU: NVIDIA GeForce RTX 3060" and cpu_result.device == "CPU"
    assert FAKE_CUPY.transfers > 0  # results came back through cupy.asnumpy
    np.testing.assert_allclose(read(gpu_result.output_path, "NDVI"), read(cpu_result.output_path, "NDVI"))
    assert gpu_result.metrics == pytest.approx(cpu_result.metrics)


def test_gpu_out_of_memory_reruns_on_the_cpu(tmp_path, monkeypatch):
    path = s2_file(tmp_path)

    class OutOfMemoryError(Exception):
        pass

    class Exploding(_FakeCupy):
        def asarray(self, array, *args, **kwargs):
            raise OutOfMemoryError("out of memory allocating 1 GB")

    gpu = [classify("NVIDIA GeForce RTX 3060")]
    service = AnalysisService(DataFacade(gemini_client=None), find_gpus=lambda: gpu,
                              select=lambda gpus, use: select_backend(gpus, use, load_cupy=Exploding))
    result = service.run_analysis(service.describe_dataset(path),
                                  AnalysisRequestDTO("Vegetation", ["NDVI"], output_dir=str(tmp_path)))
    assert result.device == "CPU" and any("ran out of memory" in note for note in result.notes)


# ------------------------------------------------------------------ availability
def test_sentinel_2_offers_optical_analyses_only(service, tmp_path):
    options = service.get_available_analyses(service.describe_dataset(s2_file(tmp_path)))
    assert [o.category for o in options] == ["Water", "Vegetation", "LST", "LULC"]
    options = {o.category: o for o in options}
    assert options["Vegetation"].available and options["Water"].available and options["LULC"].available
    assert not options["LST"].available  # Sentinel-2 has no thermal band
    assert options["LST"].label == "Land Surface Temperature"
    lst = next(p for p in options["LST"].processes if p.key == "LSTMapping")
    assert "thermal" in lst.reason and lst.group == "Surface temperature"
    spi = next(p for p in options["Vegetation"].processes if p.key == "SPI")
    assert not spi.available and "rainfall" in spi.reason and spi.group == "Moisture & drought"
    dnbr = next(p for p in options["Vegetation"].processes if p.key == "dNBR")
    assert dnbr.available and dnbr.periods == 2 and dnbr.group == "Burn & fire"
    radar = [p for p in options["LULC"].processes if p.group == "Radar (SAR)"]
    assert radar and not any(p.available for p in radar)


def test_missing_bands_are_named(service, tmp_path):
    path = write_tif(tmp_path / "Sentinel-2_1_2_2024-01-01_2024-01-31.tif",
                     {b: np.full((8, 8), 1000.0) for b in ("B2", "B3", "B4", "B8")})
    options = {o.category: o for o in service.get_available_analyses(service.describe_dataset(path))}
    ndre = next(p for p in options["Vegetation"].processes if p.key == "NDRE")
    assert not ndre.available and "red-edge 1" in ndre.reason
    with pytest.raises(AnalysisError, match="NDRE"):
        service.run_analysis(service.describe_dataset(path), AnalysisRequestDTO("Vegetation", ["NDRE"]))


# ------------------------------------------------------------------ runs
def test_ndvi_is_written_with_no_data_kept(service, tmp_path):
    path = s2_file(tmp_path)
    result = service.run_analysis(service.describe_dataset(path),
                                  AnalysisRequestDTO("Vegetation", ["NDVI"], output_dir=str(tmp_path / "out")))
    with rasterio.open(path) as src:
        nir, red = src.read(6) * 0.0001, src.read(3) * 0.0001
    ndvi = read(result.output_path, "NDVI")
    assert ndvi[0, 0] == NODATA  # red had no data there
    np.testing.assert_allclose(ndvi[1:, 1:], ((nir - red) / (nir + red))[1:, 1:], rtol=1e-5)
    assert result.metrics["NDVI mean"] == pytest.approx(float(np.mean(ndvi[ndvi != NODATA])), rel=1e-4)
    assert [layer.key for layer in result.layers] == ["NDVI"]


def test_block_size_does_not_change_the_result(tmp_path):
    path = s2_file(tmp_path)
    results = []
    for rows in (7, 1000):
        service = AnalysisService(DataFacade(gemini_client=None), find_gpus=lambda: NO_GPU, block_rows=rows)
        results.append(service.run_analysis(service.describe_dataset(path),
                                            AnalysisRequestDTO("Vegetation", ["VCI"],
                                                               output_dir=str(tmp_path / str(rows)))))
    np.testing.assert_allclose(read(results[0].output_path, "VCI"), read(results[1].output_path, "VCI"))


def test_water_mask_and_area(service, tmp_path):
    path = s2_file(tmp_path)
    result = service.run_analysis(service.describe_dataset(path), AnalysisRequestDTO(
        "Water", ["WaterBodyDetection", "WaterAreaEstimation"], output_dir=str(tmp_path / "out")))
    mask = read(result.output_path, "Water")
    assert (mask[:10] == 1).sum() >= 59 and [layer.key for layer in result.layers] == ["Water"]
    pixel_km2 = (0.0001 * 111.32) * (0.0001 * 111.32 * np.cos(np.radians(31.5)))
    water = (mask == 1).sum() * pixel_km2
    assert result.metrics["Water area (km²)"] == pytest.approx(water, rel=0.01)
    assert result.output_path.endswith(".tif")
    with open(result.output_path[:-4] + ".json", encoding="utf-8") as file:
        assert json.load(file)["processes"] == ["WaterBodyDetection", "WaterAreaEstimation"]


def test_burn_severity_needs_an_earlier_dataset(service, tmp_path):
    after = service.describe_dataset(s2_file(tmp_path, seed=1))
    with pytest.raises(AnalysisError, match="earlier dataset"):
        service.run_analysis(after, AnalysisRequestDTO("Vegetation", ["dNBR"]))
    before = service.describe_dataset(s2_file(tmp_path, "Sentinel-2_73.0150_31.4900_2023-06-01_2023-06-30.tif"))
    # Chosen the other way round: dates decide which is before.
    result = service.run_analysis(before, AnalysisRequestDTO("Vegetation", ["dNBR"], compare_with=[after],
                                                             output_dir=str(tmp_path / "out")))
    with rasterio.open(before.path) as a, rasterio.open(after.path) as b:
        nbr = lambda src: (src.read(6) - src.read(8)) / (src.read(6) + src.read(8))  # noqa: E731
        expected = nbr(a) - nbr(b)
    np.testing.assert_allclose(read(result.output_path, "dNBR")[1:], expected[1:], rtol=1e-4, atol=1e-6)


def test_lulc_transitions(service, tmp_path):
    before = np.array([[1, 1, 6, 6], [0, 0, 4, 4]], dtype=float)   # trees, built, water, crops
    after = np.array([[6, 1, 6, 6], [0, 0, 6, 4]], dtype=float)    # trees -> built, crops -> built
    a = service.describe_dataset(write_tif(tmp_path / "Dynamic-World_1_2_2020-01-01_2020-12-31.tif", {"label": before}))
    b = service.describe_dataset(write_tif(tmp_path / "Dynamic-World_1_2_2024-01-01_2024-12-31.tif", {"label": after}))
    result = service.run_analysis(b, AnalysisRequestDTO("LULC", ["LULCChangeDetection", "LULCTransition"],
                                                        compare_with=[a], output_dir=str(tmp_path / "out")))
    codes = read(result.output_path, "LULC_change")
    assert codes[0, 0] == 106 and codes[1, 2] == 406 and codes[0, 1] == 101
    pixel = result.metrics["Area compared (km²)"] / 8
    assert result.metrics["Changed area (km²)"] == pytest.approx(2 * pixel)
    assert result.metrics["Trees → Built area (km²)"] == pytest.approx(pixel)
    assert result.metrics["Crops → Built area (km²)"] == pytest.approx(pixel)
    lost = read(result.output_path, "LULC_from")
    assert lost[0, 0] == 1 and lost[0, 1] == NODATA


def test_landsat_lst_map_and_trend(service, tmp_path):
    datasets = []
    for year, kelvin in ((2019, 300.0), (2021, 302.0), (2023, 304.0)):
        raw = (kelvin - 149.0) / 0.00341802
        bands = {b: np.full((6, 6), 10000.0) for b in ("SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7")}
        bands["ST_B10"] = np.full((6, 6), raw)
        path = write_tif(tmp_path / f"Landsat-8_73.1_31.2_{year}-07-01_{year}-07-31.tif", bands)
        datasets.append(service.describe_dataset(path))
    lst = service.run_analysis(datasets[0], AnalysisRequestDTO("LST", ["LSTMapping"], output_dir=str(tmp_path)))
    assert read(lst.output_path, "LST") == pytest.approx(np.full((6, 6), 300.0 - 273.15), abs=1e-3)
    trend = service.run_analysis(datasets[2], AnalysisRequestDTO("LST", ["LSTTemporalAnalysis"],
                                                                 compare_with=datasets[:2], output_dir=str(tmp_path)))
    assert read(trend.output_path, "LST_change") == pytest.approx(np.full((6, 6), 4.0), abs=1e-3)
    assert read(trend.output_path, "LST_trend") == pytest.approx(np.full((6, 6), 1.0), abs=1e-2)  # °C per year
    assert trend.metrics["Mean LST 2019-07-01 to 2019-07-31 (°C)"] == pytest.approx(26.85, abs=1e-3)


def test_pca_and_tasseled_cap(service, tmp_path):
    rng = np.random.default_rng(3)
    bands = {b: rng.uniform(8000, 20000, (12, 12)) for b in ("SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7")}
    dataset = service.describe_dataset(write_tif(tmp_path / "Landsat-8_1_2_2024-01-01_2024-01-31.tif", bands))
    result = service.run_analysis(dataset, AnalysisRequestDTO("LULC", ["TasseledCap", "PCA"],
                                                              output_dir=str(tmp_path)))
    assert [layer.key for layer in result.layers] == ["TC_brightness", "TC_greenness", "TC_wetness", "PC1", "PC2",
                                                      "PC3"]
    shares = [result.metrics[f"PC{i} variance explained (%)"] for i in (1, 2, 3)]
    assert shares == sorted(shares, reverse=True) and sum(shares) <= 100.0 + 1e-6
    assert abs(result.metrics["PC1 mean"]) < 1e-4  # components are centred


def test_layers_are_drawn_with_legends(service, tmp_path):
    path = s2_file(tmp_path)
    result = service.run_analysis(service.describe_dataset(path), AnalysisRequestDTO(
        "Water", ["MNDWI", "WaterBodyDetection"], output_dir=str(tmp_path)))
    layers = MapService().build_layers(result, max_size=30)
    assert [layer.id for layer in layers] == ["MNDWI", "Water"]
    assert layers[0].data.shape == (layers[0].height, layers[0].width, 4) and max(layers[0].width,
                                                                                 layers[0].height) <= 30
    assert layers[0].legend.kind == "scale" and (layers[0].legend.low, layers[0].legend.high) == (-0.6, 0.6)
    assert layers[1].legend.labels == ("Water", "Land")
    assert layers[0].bounds[0] == pytest.approx(73.0)


# ------------------------------------------------------------------ facade
def test_facade_lists_finished_downloads_that_still_exist(tmp_path):
    path = s2_file(tmp_path)
    done = DownloadJobDTO("1", "Sentinel-2_73.0150_31.4900_2024-06-01_2024-06-30", str(tmp_path), JOB_COMPLETED,
                          dataset=DatasetDTO("1", "COPERNICUS/S2_SR_HARMONIZED", path), finished_at="2024-07-01")
    gone = DownloadJobDTO("2", "x", str(tmp_path), JOB_COMPLETED, dataset=DatasetDTO("2", "", str(tmp_path / "x.tif")))
    failed = DownloadJobDTO("3", "y", str(tmp_path), JOB_FAILED)
    downloads = MagicMock()
    downloads.list_jobs.return_value = [gone, failed, done]
    requests = MagicMock()
    requests.get_current_project.return_value = ProjectDTO(id="p1", name="P", folder=str(tmp_path))
    facade = BusinessFacade(MagicMock(), requests, downloads, MapService(), MagicMock())
    [dataset] = facade.list_analysis_datasets()
    assert (dataset.path, dataset.satellite, dataset.start_date) == (path, "Sentinel-2", "2024-06-01")


def test_facade_lists_only_the_open_projects_datasets(tmp_path):
    for project in ("Mine", "Other"):
        (tmp_path / project / "downloads").mkdir(parents=True)
    mine = s2_file(tmp_path / "Mine" / "downloads")
    theirs = s2_file(tmp_path / "Other" / "downloads")
    jobs = [DownloadJobDTO(str(n), "Sentinel-2_73.0150_31.4900_2024-06-01_2024-06-30", str(Path(p).parent),
                           JOB_COMPLETED, dataset=DatasetDTO(str(n), "", p)) for n, p in enumerate((mine, theirs))]
    downloads = MagicMock()
    downloads.list_jobs.return_value = jobs
    requests = MagicMock()
    facade = BusinessFacade(MagicMock(), requests, downloads, MapService(), MagicMock())
    requests.get_current_project.return_value = ProjectDTO(id="p1", name="Mine", folder=str(tmp_path / "Mine"))
    assert [d.path for d in facade.list_analysis_datasets()] == [mine]
    requests.get_current_project.return_value = None
    assert facade.list_analysis_datasets() == []  # no project: nothing to analyse


def test_facade_without_analysis_service_says_so():
    facade = BusinessFacade(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    with pytest.raises(AnalysisError, match="not set up"):
        facade.list_formulas()


def test_cpu_backend_moves_arrays_unchanged():
    backend: ComputeBackend = cpu_backend()
    array = np.arange(4.0)
    assert backend.to_host(backend.to_device(array)) is not None and backend.label() == "CPU"


# ------------------------------------------------------------------ saving only on request
def test_results_are_temporary_until_saved(service, tmp_path):
    from backend.config import DEFAULT_ANALYSIS_DIR

    dataset = service.describe_dataset(s2_file(tmp_path))
    before = set(DEFAULT_ANALYSIS_DIR.glob("*")) if DEFAULT_ANALYSIS_DIR.exists() else set()
    result = service.run_analysis(dataset, AnalysisRequestDTO("Vegetation", ["NDVI"]))
    temporary = Path(result.output_path)
    assert not result.saved and temporary.is_file() and temporary.with_suffix(".json").is_file()
    assert DEFAULT_ANALYSIS_DIR not in temporary.parents
    assert (set(DEFAULT_ANALYSIS_DIR.glob("*")) if DEFAULT_ANALYSIS_DIR.exists() else set()) == before

    saved = service.save_result(result, str(tmp_path / "kept" / "my_ndvi"))
    assert saved.saved and saved.output_path == str(tmp_path / "kept" / "my_ndvi.tif")
    assert Path(saved.output_path).is_file() and (tmp_path / "kept" / "my_ndvi.json").is_file()
    assert not temporary.exists()  # the temporary copy is gone
    service.discard_result(saved)
    assert Path(saved.output_path).is_file()  # saved results are never discarded


def test_unsaved_results_can_be_discarded_and_are_cleaned_up(service, tmp_path):
    dataset = service.describe_dataset(s2_file(tmp_path))
    first = service.run_analysis(dataset, AnalysisRequestDTO("Vegetation", ["NDVI"]))
    service.discard_result(first)
    assert not Path(first.output_path).exists()
    second = service.run_analysis(dataset, AnalysisRequestDTO("Water", ["NDWI"]))
    folder = Path(second.output_path).parent
    service.cleanup()
    assert not folder.exists()
    with pytest.raises(AnalysisError, match="no longer there"):
        service.save_result(second, str(tmp_path / "late.tif"))


def test_an_explicit_folder_counts_as_saved(service, tmp_path):
    result = service.run_analysis(service.describe_dataset(s2_file(tmp_path)),
                                  AnalysisRequestDTO("Vegetation", ["NDVI"], output_dir=str(tmp_path / "out")))
    assert result.saved and Path(result.output_path).parent == tmp_path / "out"


def test_saving_works_while_the_temporary_result_is_still_open(service, tmp_path):
    """The map layers may still be reading the temporary file when Save is pressed (WinError 32 on Windows)."""
    dataset = service.describe_dataset(s2_file(tmp_path))
    result = service.run_analysis(dataset, AnalysisRequestDTO("Vegetation", ["NDVI", "EVI"]))
    with rasterio.open(result.output_path):  # e.g. the map layers being drawn from it
        saved = service.save_result(result, str(tmp_path / "project" / "analysis" / "result.tif"))
    assert saved.saved and Path(saved.output_path).is_file()
    folder = Path(result.output_path).parent
    service.cleanup()  # whatever could not be deleted then goes when the app closes
    assert not folder.exists()


def test_datasets_lined_up_with_the_reference_are_closed_after_a_run(service, tmp_path):
    import os

    before = s2_file(tmp_path, "Sentinel-2_73.0150_31.4900_2023-06-01_2023-06-30.tif", seed=1, shape=(30, 50))
    after = service.describe_dataset(s2_file(tmp_path))
    service.run_analysis(after, AnalysisRequestDTO("Vegetation", ["dNBR"],
                                                   compare_with=[service.describe_dataset(before)]))
    os.rename(before, before + ".moved")  # fails on Windows while any handle on it is still open


# ------------------------------------------------------------------ result file names
def test_result_names_list_the_processes(service, tmp_path):
    import re

    dataset = service.describe_dataset(s2_file(tmp_path))
    result = service.run_analysis(dataset, AnalysisRequestDTO("Vegetation", ["NDVI", "EVI"]))
    name = Path(result.output_path).name
    assert re.fullmatch(r"Sentinel-2_73\.0150_31\.4900_2024-06-01_2024-06-30_Vegetation_NDVI_EVI_"
                        r"\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d\.tif", name), name


def test_many_processes_are_shortened_in_the_name():
    from backend.business.analysis.base_analysis import PROCESSES_IN_NAME, processes_part

    assert processes_part(["NDVI"]) == "NDVI"
    many = ["NDVI", "EVI", "SAVI", "MSAVI", "GNDVI", "NDRE", "GCI", "CIre", "MTCI", "MCARI", "TCARI", "ARVI",
            "VARI", "RVI", "DVI", "WDRVI", "PSRI", "LAI", "FAPAR", "FCover"]
    part = processes_part(many)
    assert len(part) <= PROCESSES_IN_NAME and part.startswith("NDVI_EVI_SAVI")
    shown = part.split("_and_")[0].split("_")
    assert part.endswith(f"_and_{len(many) - len(shown)}_more") and shown == many[:len(shown)]
