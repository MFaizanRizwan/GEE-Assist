from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppVersionDTO:
    latest_version: str
    minimum_supported_version: str
    download_url: str | None = None
    release_notes: str | None = None
    force_update: bool = False
    update_available: bool = False
    published_at: str | None = None
    sha256: str | None = None   # the release .exe's SHA-256, checked after downloading (optional)
