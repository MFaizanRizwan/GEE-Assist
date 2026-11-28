"""Where the Prediction page trains: an NVIDIA GPU (CUDA) for the libraries that can use it, else the CPU.

Only two of the libraries train on a GPU:

* **XGBoost** - when its build has CUDA (the standard Windows/Linux pip wheels do);
* **PyTorch** - when it is a CUDA build and sees the card (``torch.cuda.is_available()``).

scikit-learn has no GPU support, and LightGBM's GPU mode (OpenCL) needs a custom build, so
their algorithms always train on the CPU. Graphics cards are found with the same lookup the
Analysis page uses (``analysis.compute_device``). When the GPU cannot be used, ``reason``
says why and, where possible, how to enable it.
"""

from __future__ import annotations

import importlib.util
import logging
from functools import lru_cache
from typing import Callable

from backend.dto.analysis_dto import GpuDTO
from backend.dto.prediction_dto import PredictionDeviceDTO

logger = logging.getLogger(__name__)

XGBOOST, PYTORCH = "xgboost", "pytorch"                  # library names as in algorithms.Spec.library
GPU_LIBRARIES = (XGBOOST, PYTORCH)
LIBRARY_LABELS = {XGBOOST: "XGBoost", PYTORCH: "PyTorch"}
TORCH_CUDA_HINT = "pip install torch --index-url https://download.pytorch.org/whl/cu124"


@lru_cache(maxsize=1)
def xgboost_has_cuda() -> bool:
    """Whether the installed XGBoost was built with CUDA."""
    if importlib.util.find_spec("xgboost") is None:
        return False
    try:
        import xgboost

        return bool(xgboost.build_info().get("USE_CUDA"))
    except Exception:  # noqa: BLE001 - a broken install only means "no GPU"
        logger.exception("Could not read XGBoost's build info")
        return False


@lru_cache(maxsize=1)
def torch_cuda_device() -> str:
    """The CUDA card PyTorch can train on ("" when it is a CPU build or sees no card)."""
    if importlib.util.find_spec("torch") is None:
        return ""
    try:
        import torch

        return torch.cuda.get_device_name(0) if torch.cuda.is_available() else ""
    except Exception:  # noqa: BLE001 - a broken driver / CUDA install: the CPU still works
        logger.exception("PyTorch could not start CUDA")
        return ""


def torch_is_installed() -> bool:
    return importlib.util.find_spec("torch") is not None


def select_prediction_device(
    gpus: list[GpuDTO] | tuple[GpuDTO, ...],
    use_gpu: bool = True,
    xgboost_cuda: Callable[[], bool] = xgboost_has_cuda,
    torch_cuda: Callable[[], str] = torch_cuda_device,
    torch_installed: Callable[[], bool] = torch_is_installed,
) -> PredictionDeviceDTO:
    """Which libraries train on the GPU (if any), with the reason shown on the page."""
    gpus = tuple(gpus)
    nvidia = [gpu for gpu in gpus if gpu.vendor == "NVIDIA" and gpu.is_dedicated]
    torch_card = torch_cuda() if (nvidia and use_gpu) else ""
    if not nvidia:
        names = ", ".join(gpu.name for gpu in gpus) or "none found"
        return PredictionDeviceDTO("CPU", (), gpus, f"No NVIDIA GPU (graphics: {names}), so every model trains "
                                                    "on the CPU.")
    card = nvidia[0].name
    if not use_gpu:
        return PredictionDeviceDTO("CPU", (), gpus, f"GPU turned off: {card} is not used.")

    on_gpu = tuple(lib for lib, ok in ((XGBOOST, xgboost_cuda()), (PYTORCH, bool(torch_card))) if ok)
    torch_hint = ""
    if PYTORCH not in on_gpu and torch_installed():
        torch_hint = (f" PyTorch is a CPU-only build, so its deep-learning models use the CPU; for the GPU, "
                      f"run: {TORCH_CUDA_HINT}")
    if not on_gpu:
        return PredictionDeviceDTO("CPU", (), gpus, f"{card} found, but no installed library can train on it."
                                                    + torch_hint)
    names = " and ".join(LIBRARY_LABELS[lib] for lib in on_gpu)
    return PredictionDeviceDTO(
        torch_card or card, on_gpu, gpus,
        f"{names} models train on {torch_card or card}; scikit-learn and LightGBM models use the CPU."
        + torch_hint)


def place_on_device(estimator, library: str, gpu: bool) -> None:
    """Point an XGBoost / PyTorch estimator at the GPU (``gpu``) or the CPU; others are left as they are."""
    if library == XGBOOST:
        estimator.set_params(device="cuda" if gpu else "cpu")
    elif library == PYTORCH and hasattr(estimator, "device"):
        estimator.device = "cuda" if gpu else "cpu"
