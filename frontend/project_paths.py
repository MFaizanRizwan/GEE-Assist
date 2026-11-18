"""The open project and its folders, as the UI needs them (with the old defaults when none is open)."""

from __future__ import annotations

from backend.config import DEFAULT_ANALYSIS_DIR, DEFAULT_DOWNLOAD_DIR
from backend.dto.project_dto import ProjectDTO


def current_project(facade) -> ProjectDTO | None:
    project = facade.get_current_project()
    return project if isinstance(project, ProjectDTO) else None


def downloads_folder(facade) -> str:
    """Where to start looking for GeoTIFFs: the open project's downloads folder."""
    project = current_project(facade)
    return project.downloads_dir if project is not None else str(DEFAULT_DOWNLOAD_DIR)


def analysis_folder(facade) -> str:
    """Where analysis results are saved: the open project's analysis folder."""
    project = current_project(facade)
    return project.analysis_dir if project is not None else str(DEFAULT_ANALYSIS_DIR)
