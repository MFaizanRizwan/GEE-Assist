from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable


class IUpdateService(ABC):
    """Updates the app to a new version: downloads its installer and starts it."""

    @abstractmethod
    def download_update(
        self,
        url: str,
        on_progress: Callable[[int, int | None], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Path:
        """Download the installer at ``url`` and return where it was saved.

        ``on_progress(received, total)`` is called as bytes arrive (``total`` is None when the
        server does not say). Raises ``UpdateCancelledError`` once ``is_cancelled()`` is true,
        ``UpdateError`` when the download fails or is not an installer."""

    @abstractmethod
    def install_update(self, installer: Path) -> None:
        """Start the downloaded installer. The app should then quit so its files can be replaced."""
