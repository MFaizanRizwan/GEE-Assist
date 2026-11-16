"""DTOs shared by the frontend and backend (names follow the SRS class diagram)."""

from backend.dto.check_dto import CheckDTO
from backend.dto.download_dto import ChunkDTO, DatasetDTO, DownloadJobDTO
from backend.dto.place_dto import PlaceDTO
from backend.dto.request_dto import EntityDTO, FormDTO
from backend.dto.validation_dto import ValidationDTO
from backend.dto.version_dto import AppVersionDTO

__all__ = [
    "AppVersionDTO",
    "CheckDTO",
    "ChunkDTO",
    "DatasetDTO",
    "DownloadJobDTO",
    "EntityDTO",
    "FormDTO",
    "PlaceDTO",
    "ValidationDTO",
]
