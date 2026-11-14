"""Finds the computer's graphics cards and picks where analyses run: GPU or CPU.

Graphics cards are listed with Windows' WMI (``Win32_VideoController``) and, when the
NVIDIA driver is installed, ``nvidia-smi`` (which also gives the true memory size;
WMI caps it at 4 GB). Each card is classed as dedicated, integrated or virtual from
its name.

Analyses use the same array code on either device (``backend.xp`` is NumPy or CuPy).
The GPU is used when there is a dedicated NVIDIA card, CuPy is installed and CUDA
answers; otherwise the CPU, and ``ComputeDeviceDTO.reason`` says why (e.g. how to
install CuPy). AMD and Intel cards cannot run CuPy on Windows, so they use the CPU.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
from functools import lru_cache
from typing import Any, Callable

import numpy as np

from backend.dto.analysis_dto import (
    GPU_DEDICATED,
    GPU_INTEGRATED,
    GPU_VIRTUAL,
    ComputeDeviceDTO,
    GpuDTO,
)

logger = logging.getLogger(__name__)

CUPY_HINT = "pip install cupy-cuda12x"  # CUDA 12 build; cupy-cuda11x for older drivers
_TIMEOUT_S = 8

Runner = Callable[[list[str]], str]  # runs a command, returns its standard output ("" on failure)


# ----------------------------------------------------------------------------- detection
def _run(command: list[str]) -> str:
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console window flashes up on Windows
        done = subprocess.run(command, capture_output=True, text=True, timeout=_TIMEOUT_S, creationflags=flags)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def detect_gpus(run: Runner = _run, platform: str = sys.platform) -> list[GpuDTO]:
    """Every graphics card found, dedicated ones first."""
    gpus: dict[str, GpuDTO] = {}
    if platform.startswith("win"):
        for gpu in _from_wmi(run([
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object Name, AdapterCompatibility, AdapterRAM "
            "| ConvertTo-Json -Compress",
        ])):
            gpus[gpu.name] = gpu
    if platform.startswith("win") or shutil.which("nvidia-smi"):
        for gpu in _from_nvidia_smi(run(["nvidia-smi", "--query-gpu=name,memory.total",
                                         "--format=csv,noheader,nounits"])):
            gpus[gpu.name] = gpu  # more exact memory than WMI
    order = {GPU_DEDICATED: 0, GPU_INTEGRATED: 1, GPU_VIRTUAL: 2}
    return sorted(gpus.values(), key=lambda gpu: order[gpu.kind])


def _from_wmi(output: str) -> list[GpuDTO]:
    try:
        rows: Any = json.loads(output) if output.strip() else []
    except json.JSONDecodeError:
        return []
    if isinstance(rows, dict):  # one card: PowerShell gives an object, not a list
        rows = [rows]
    gpus = []
    for row in rows:
        name = str(row.get("Name") or "").strip()
        if not name:
            continue
        memory = row.get("AdapterRAM") or 0
        gpus.append(classify(name, str(row.get("AdapterCompatibility") or ""), int(memory) if memory > 0 else 0))
    return gpus


def _from_nvidia_smi(output: str) -> list[GpuDTO]:
    gpus = []
    for line in output.splitlines():
        name, _, memory = line.partition(",")
        if name.strip():
            mib = memory.strip()
            gpus.append(classify(name.strip(), "NVIDIA", int(mib) * 1024 * 1024 if mib.isdigit() else 0))
    return gpus


_INTEGRATED_AMD = re.compile(r"radeon graphics|vega \d+|radeon \d{3}m")  # APU graphics: Ryzen's built-in GPU
_DEDICATED_AMD = re.compile(r"rx ?\d|radeon pro|firepro|instinct|radeon vii")


def classify(name: str, vendor_hint: str = "", memory_bytes: int = 0) -> GpuDTO:
    """A graphics card from its name: who makes it and whether it is dedicated, integrated or virtual."""
    lower = " ".join(re.sub(r"\((tm|r)\)|™|®", " ", name.lower()).split())  # "AMD Radeon (TM) Graphics"
    text = f"{lower} {vendor_hint.lower()}"
    if any(word in text for word in ("nvidia", "geforce", "quadro", "tesla", "rtx", "gtx")):
        return GpuDTO(name, "NVIDIA", GPU_DEDICATED, memory_bytes)  # NVIDIA only makes discrete GPUs for PCs
    if any(word in text for word in ("amd", "radeon", "advanced micro devices", "ati ")):
        dedicated = bool(_DEDICATED_AMD.search(lower)) and not _INTEGRATED_AMD.search(lower)
        return GpuDTO(name, "AMD", GPU_DEDICATED if dedicated else GPU_INTEGRATED, memory_bytes)
    if "intel" in text:
        dedicated = "arc a" in lower or "arc pro" in lower or "arc b" in lower
        return GpuDTO(name, "Intel", GPU_DEDICATED if dedicated else GPU_INTEGRATED, memory_bytes)
    if any(word in text for word in ("microsoft", "basic display", "remote", "virtual", "vmware", "parsec")):
        return GpuDTO(name, "Microsoft" if "microsoft" in text else vendor_hint or "Virtual", GPU_VIRTUAL,
                      memory_bytes)
    return GpuDTO(name, vendor_hint or "Unknown", GPU_INTEGRATED, memory_bytes)


# ----------------------------------------------------------------------------- the backend
def _load_cupy():
    import cupy  # optional dependency: only on computers with an NVIDIA GPU

    if cupy.cuda.runtime.getDeviceCount() < 1:
        raise RuntimeError("CUDA sees no GPU")
    return cupy


class ComputeBackend:
    """The array library analyses compute with, and moving arrays to and from its device."""

    def __init__(self, xp, device: ComputeDeviceDTO):
        self.xp = xp
        self.device = device

    @property
    def uses_gpu(self) -> bool:
        return self.device.uses_gpu

    def to_device(self, array: np.ndarray):
        return self.xp.asarray(array)

    def to_host(self, array) -> np.ndarray:
        if self.xp is np:
            return np.asarray(array)
        return self.xp.asnumpy(array)

    def scalar(self, value) -> float:
        return float(value.item() if hasattr(value, "item") else value)

    def free(self) -> None:
        """Give cached GPU memory back (CuPy keeps freed blocks for reuse)."""
        if self.xp is not np:
            try:
                self.xp.get_default_memory_pool().free_all_blocks()
            except Exception:  # noqa: BLE001 - only a clean-up
                pass

    def label(self) -> str:
        return f"GPU: {self.device.device_name}" if self.uses_gpu else "CPU"


def cpu_backend(gpus: tuple[GpuDTO, ...] = (), reason: str = "") -> ComputeBackend:
    return ComputeBackend(np, ComputeDeviceDTO("numpy", "CPU", gpus, reason))


def select_backend(
    gpus: list[GpuDTO] | tuple[GpuDTO, ...],
    use_gpu: bool = True,
    load_cupy: Callable[[], Any] = _load_cupy,
) -> ComputeBackend:
    """CuPy on the first dedicated NVIDIA GPU when it works; NumPy otherwise, with the reason."""
    gpus = tuple(gpus)
    dedicated = [gpu for gpu in gpus if gpu.is_dedicated]
    if not dedicated:
        names = ", ".join(gpu.name for gpu in gpus) or "none found"
        return cpu_backend(gpus, f"No dedicated GPU (graphics: {names}), so analyses run on the CPU.")
    nvidia = [gpu for gpu in dedicated if gpu.vendor == "NVIDIA"]
    if not nvidia:
        return cpu_backend(gpus, f"{dedicated[0].name} is a dedicated GPU, but GPU computing needs an NVIDIA "
                                 "card (CUDA), so analyses run on the CPU.")
    if not use_gpu:
        return cpu_backend(gpus, f"GPU turned off: {nvidia[0].name} is not used.")
    try:
        cupy = load_cupy()
    except ImportError:
        return cpu_backend(gpus, f"{nvidia[0].name} found, but CuPy is not installed. To use it, run: "
                                 f"{CUPY_HINT}")
    except Exception as exc:  # noqa: BLE001 - a broken driver or CUDA install: the CPU still works
        logger.warning("CuPy is installed but CUDA failed: %s", exc)
        return cpu_backend(gpus, f"{nvidia[0].name} found, but CUDA did not start ({exc}). Update the NVIDIA "
                                 "driver or reinstall CuPy.")
    return ComputeBackend(cupy, ComputeDeviceDTO("cupy", nvidia[0].name, gpus,
                                                 f"Analyses run on {nvidia[0].name} with CuPy."))


@lru_cache(maxsize=1)
def cached_gpus() -> tuple[GpuDTO, ...]:
    """The graphics cards, looked up once per run of the app (it takes about a second)."""
    try:
        return tuple(detect_gpus())
    except Exception:  # noqa: BLE001 - detection is a convenience; the CPU always works
        logger.exception("Could not list the graphics cards")
        return ()
