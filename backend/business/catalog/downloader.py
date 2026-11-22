"""Download files from data providers over HTTP and safely extract zipped shapefiles.

Uses httpx (already a dependency) with streaming, so progress is reported while the file
arrives. Archives are treated as untrusted: each is extracted into a fresh directory and any
member whose path escapes it (absolute paths, ``..``) is skipped.
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path
from typing import Callable, Optional

import httpx

from backend.exceptions import CatalogError

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int], None]  # (bytes received, total bytes; total 0 = unknown)
USER_AGENT = "GEE-Assist/1.0 (desktop GIS; data catalog)"
CHUNK = 64 * 1024


def download_file(url: str, dest: str | Path, on_progress: Optional[ProgressCallback] = None,
                  headers: dict | None = None, timeout: float = 120.0) -> Path:
    """Stream ``url`` to ``dest``; returns the path written. ``CatalogError`` on any failure."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=timeout, headers=request_headers) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length") or 0)
            received = 0
            with open(dest, "wb") as handle:
                for block in response.iter_bytes(CHUNK):
                    handle.write(block)
                    received += len(block)
                    if on_progress is not None:
                        on_progress(received, total)
    except httpx.HTTPStatusError as exc:
        _cleanup(dest)
        raise CatalogError(f"The provider returned HTTP {exc.response.status_code} for {url}.") from exc
    except (httpx.HTTPError, OSError) as exc:
        _cleanup(dest)
        raise CatalogError(f"The download failed: {exc}") from exc
    if dest.stat().st_size == 0:
        _cleanup(dest)
        raise CatalogError("The provider returned an empty file.")
    return dest


def download_and_extract(url: str, dest_dir: str | Path, on_progress: Optional[ProgressCallback] = None,
                         headers: dict | None = None) -> list[Path]:
    """Download a zip from ``url`` and extract it into ``dest_dir``; returns the extracted file paths.

    A non-zip download is kept as a single file. ``dest_dir`` should be a fresh, empty directory.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    archive = dest_dir / _file_name(url)
    download_file(url, archive, on_progress=on_progress, headers=headers)
    if not zipfile.is_zipfile(archive):
        return [archive]
    extracted = _safe_extract(archive, dest_dir)
    archive.unlink(missing_ok=True)  # keep only the extracted files
    if not extracted:
        raise CatalogError("The downloaded archive was empty.")
    return extracted


def fetch_json(url: str, params: dict | None = None, timeout: float = 30.0) -> dict:
    """GET a JSON document (a provider's search/catalog API). ``CatalogError`` on failure."""
    try:
        response = httpx.get(url, params=params, follow_redirects=True, timeout=timeout,
                             headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise CatalogError(f"The provider's API returned HTTP {exc.response.status_code}.") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise CatalogError(f"The provider's API could not be reached: {exc}") from exc


# ------------------------------------------------------------- helpers
def _safe_extract(archive: Path, dest_dir: Path) -> list[Path]:
    extracted: list[Path] = []
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            target = (dest_dir / member.filename).resolve()
            if dest_dir.resolve() not in target.parents and target != dest_dir.resolve():
                logger.warning("Skipping archive member outside the target directory: %s", member.filename)
                continue  # zip-slip guard
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as source, open(target, "wb") as out:
                while True:
                    block = source.read(CHUNK)
                    if not block:
                        break
                    out.write(block)
            extracted.append(target)
    return extracted


def _file_name(url: str) -> str:
    name = url.split("?")[0].rstrip("/").split("/")[-1]
    return name or "download.bin"


def _cleanup(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
