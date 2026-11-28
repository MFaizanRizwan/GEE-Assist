"""GPU support on the Prediction page: which libraries train on the GPU, falling back to the CPU."""

import pytest

pytest.importorskip("rasterio")
pytest.importorskip("sklearn")

from backend.business.prediction import PredictionService  # noqa: E402
from backend.business.prediction import prediction_service as service_module  # noqa: E402
from backend.business.prediction.device import place_on_device, select_prediction_device  # noqa: E402
from backend.dto.analysis_dto import GPU_DEDICATED, GPU_INTEGRATED, GpuDTO  # noqa: E402
from backend.dto.prediction_dto import FORECAST, PredictionDeviceDTO, PredictionRequestDTO  # noqa: E402
from tests.test_prediction_service import _ndvi_series, _options  # noqa: E402

RTX = GpuDTO("NVIDIA GeForce RTX 3060", "NVIDIA", GPU_DEDICATED, 12 << 30)
IRIS = GpuDTO("Intel(R) Iris(R) Xe Graphics", "Intel", GPU_INTEGRATED)
RADEON = GpuDTO("AMD Radeon RX 6700 XT", "AMD", GPU_DEDICATED)


def _select(gpus, use_gpu=True, xgb=True, torch_card="NVIDIA GeForce RTX 3060", torch_installed=True):
    return select_prediction_device(gpus, use_gpu, xgboost_cuda=lambda: xgb, torch_cuda=lambda: torch_card,
                                    torch_installed=lambda: torch_installed)


# ------------------------------------------------------------- choosing the device
def test_without_an_nvidia_card_everything_trains_on_the_cpu():
    for gpus in ([], [IRIS], [IRIS, RADEON]):
        device = _select(gpus)
        assert not device.uses_gpu and device.device_name == "CPU" and not device.has_nvidia
        assert "No NVIDIA GPU" in device.reason


def test_an_nvidia_card_trains_xgboost_and_pytorch_on_the_gpu():
    device = _select([IRIS, RTX])
    assert device.uses_gpu and device.has_nvidia
    assert device.gpu_libraries == ("xgboost", "pytorch")
    assert device.device_name == "NVIDIA GeForce RTX 3060"
    assert "scikit-learn and LightGBM models use the CPU" in device.reason


def test_a_cpu_only_pytorch_says_how_to_get_the_gpu_build():
    device = _select([RTX], torch_card="")
    assert device.gpu_libraries == ("xgboost",)
    assert "CPU-only build" in device.reason and "download.pytorch.org/whl/cu" in device.reason


def test_no_cuda_library_or_turned_off_means_the_cpu():
    none = _select([RTX], xgb=False, torch_card="")
    assert not none.uses_gpu and none.has_nvidia and "no installed library" in none.reason
    off = _select([RTX], use_gpu=False)
    assert not off.uses_gpu and off.has_nvidia and "turned off" in off.reason


def test_estimators_are_pointed_at_the_chosen_device():
    xgboost = pytest.importorskip("xgboost")
    model = xgboost.XGBRegressor()
    place_on_device(model, "xgboost", True)
    assert model.get_params()["device"] == "cuda"
    place_on_device(model, "xgboost", False)
    assert model.get_params()["device"] == "cpu"

    pytest.importorskip("torch")
    from backend.business.prediction.torch_models import TorchRegressor

    net = TorchRegressor()
    assert net.device == "cpu"                     # the CPU unless the service says otherwise
    place_on_device(net, "pytorch", True)
    assert net.device == "cuda" and net.get_params()["device"] == "cuda"   # survives cloning (tuning)


def test_a_pytorch_model_asked_for_cuda_without_one_still_trains_on_the_cpu():
    torch = pytest.importorskip("torch")
    import numpy as np

    from backend.business.prediction.torch_models import TorchRegressor, _device

    if torch.cuda.is_available():
        pytest.skip("this computer has CUDA")
    assert _device(torch, "cuda").type == "cpu"
    x = np.random.default_rng(0).normal(size=(200, 3)).astype("float32")
    model = TorchRegressor(device="cuda").fit(x, x.sum(axis=1))
    assert model.predict(x).shape == (200,)


# ------------------------------------------------------------- training on it
FAKE_GPU = PredictionDeviceDTO("NVIDIA GeForce RTX 3060", ("xgboost", "pytorch"), (RTX,), "")


def _forecast(tmp_path, service, algorithms, use_gpu=True):
    inputs, _truth = _ndvi_series(tmp_path)
    request = PredictionRequestDTO(FORECAST, inputs, band="NDVI", target_date="2025-06-01",
                                   algorithms=algorithms, options=_options(lags=2, use_gpu=use_gpu))
    return service.run(request)


def test_gpu_models_are_marked_and_the_result_says_where_it_trained(tmp_path, monkeypatch):
    pytest.importorskip("xgboost")
    placed = []
    monkeypatch.setattr(service_module, "place_on_device",
                        lambda estimator, library, gpu: placed.append((library, gpu)))   # no real CUDA here
    service = PredictionService(find_gpus=lambda: (RTX,), select_device=lambda gpus, use_gpu: FAKE_GPU)
    result = _forecast(tmp_path, service, ["persistence", "linear", "xgboost"])
    by_key = {s.key: s for s in result.scores}
    assert by_key["xgboost"].device == "GPU"
    assert by_key["linear"].device == "" and by_key["persistence"].device == ""   # scikit-learn / baseline: CPU
    assert ("xgboost", True) in placed and ("scikit-learn", True) not in placed
    assert result.device == "GPU: NVIDIA GeForce RTX 3060"


def test_a_model_that_fails_on_the_gpu_trains_again_on_the_cpu(tmp_path, monkeypatch):
    pytest.importorskip("xgboost")

    def place(estimator, library, gpu):
        if gpu:
            raise RuntimeError("CUDA out of memory")
        place_on_device(estimator, library, False)

    monkeypatch.setattr(service_module, "place_on_device", place)
    service = PredictionService(find_gpus=lambda: (RTX,), select_device=lambda gpus, use_gpu: FAKE_GPU)
    result = _forecast(tmp_path, service, ["persistence", "xgboost"])
    xgb = next(s for s in result.scores if s.key == "xgboost")
    assert not xgb.error and xgb.device == "" and xgb.metrics     # it ran, on the CPU
    assert result.device == "CPU"
    assert any("XGBoost" in note and "CUDA out of memory" in note and "CPU" in note for note in result.notes)


def test_turning_the_gpu_off_keeps_every_model_on_the_cpu(tmp_path, monkeypatch):
    pytest.importorskip("xgboost")
    asked = []

    def select(gpus, use_gpu):
        asked.append(use_gpu)
        return FAKE_GPU if use_gpu else PredictionDeviceDTO("CPU", (), (RTX,), "GPU turned off")

    service = PredictionService(find_gpus=lambda: (RTX,), select_device=select)
    result = _forecast(tmp_path, service, ["persistence", "xgboost"], use_gpu=False)
    assert asked == [False]
    assert result.device == "CPU" and all(s.device == "" for s in result.scores)
