"""Class diagram: ProjectDAO. Project folders on this computer, and a JSON history of where they are."""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any

from backend.data.dao.i_project_dao import IProjectDAO
from backend.dto.project_dto import (
    ANALYSIS_FOLDER,
    ANALYSIS_RESULTS_FILE,
    DOWNLOADS_FOLDER,
    EXPLANATION_FOLDER,
    PROJECT_FILE,
    REPORTS_FOLDER,
    AnalysisRecordDTO,
    ProjectDTO,
)
from backend.exceptions import ProjectError

logger = logging.getLogger(__name__)

HISTORY_VERSION = 1


class ProjectDAO(IProjectDAO):
    def __init__(self, history_path: Path | str):
        """``history_path``: the JSON file that remembers the project folders (e.g. workspace/projects.json)."""
        self._history_path = Path(history_path)
        self._lock = threading.RLock()

    # ------------------------------------------------------------- the diagram's CRUD
    def save(self, entity: ProjectDTO) -> bool:
        folder = Path(entity.folder)
        try:
            for sub in (DOWNLOADS_FOLDER, ANALYSIS_FOLDER, EXPLANATION_FOLDER, REPORTS_FOLDER):
                (folder / sub).mkdir(parents=True, exist_ok=True)
            _write_json(folder / PROJECT_FILE, {"app": "GEE-Assist", "id": entity.id, "name": entity.name,
                                                "created_at": entity.created_at})
        except OSError as exc:
            raise ProjectError(f"Could not write the project folder {folder}: {exc.strerror or exc}") from exc
        with self._lock:
            projects = [p for p in self._read_history() if p.id != entity.id]
            projects.insert(0, entity)
            self._write_history(projects)
        return True

    def find_by_id(self, id: str) -> ProjectDTO | None:  # noqa: A002
        return next((p for p in self.find_all() if p.id == id), None)

    def find_by_user_id(self, user_id: str) -> list[ProjectDTO]:
        return [p for p in self.find_all() if p.owner_id == user_id]

    def find_all(self) -> list[ProjectDTO]:
        with self._lock:
            projects = self._read_history()
        return sorted(projects, key=lambda p: p.last_opened_at or p.created_at, reverse=True)

    def delete(self, id: str) -> bool:  # noqa: A002
        with self._lock:
            projects = self._read_history()
            kept = [p for p in projects if p.id != id]
            if len(kept) == len(projects):
                return False
            self._write_history(kept)
        return True

    # ------------------------------------------------------------- folders
    def load_folder(self, folder: str) -> ProjectDTO | None:
        path = Path(folder) / PROJECT_FILE
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise ProjectError(f"The project file {path} cannot be read.") from exc
        if not isinstance(data, dict):
            raise ProjectError(f"The project file {path} cannot be read.")
        known = self.find_by_id(str(data.get("id", "")))
        return ProjectDTO(
            id=str(data.get("id") or uuid.uuid4().hex[:12]),
            name=str(data.get("name") or Path(folder).name),
            folder=str(Path(folder).resolve()),
            owner_id=known.owner_id if known else "",
            created_at=str(data.get("created_at", "")),
            last_opened_at=known.last_opened_at if known else "",
        )

    def move(self, entity: ProjectDTO, new_folder: str) -> ProjectDTO:
        old, new = Path(entity.folder), Path(new_folder)
        try:
            if _same_place(old, new):
                # Only the letter case changes (Windows sees one folder): go through a temporary name.
                temporary = old.with_name(f"{old.name}.renaming-{uuid.uuid4().hex[:6]}")
                os.rename(old, temporary)
                os.rename(temporary, new)
            else:
                new.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old), str(new))
        except OSError as exc:
            raise ProjectError(
                f"Could not move the project to {new}: {exc.strerror or exc}. "
                "Close any of its files that are open in other programs and try again."
            ) from exc
        moved = ProjectDTO(id=entity.id, name=entity.name, folder=str(new.resolve()), owner_id=entity.owner_id,
                           created_at=entity.created_at, last_opened_at=entity.last_opened_at)
        self.save(moved)
        return moved

    # ------------------------------------------------------------- analysis results
    def save_analysis_result(self, project: ProjectDTO, record: AnalysisRecordDTO) -> bool:
        path = self._results_path(project)
        with self._lock:
            records = [r for r in self._read_results(path) if r.id != record.id]
            records.append(record)
            try:
                _write_json(path, {"project_id": project.id, "results": [r.to_dict() for r in records]})
            except OSError as exc:
                raise ProjectError(f"Could not save the analysis result in {path}: {exc.strerror or exc}") from exc
        return True

    def find_analysis_results(self, project: ProjectDTO) -> list[AnalysisRecordDTO]:
        with self._lock:
            records = self._read_results(self._results_path(project))
        return sorted(records, key=lambda r: r.created_at, reverse=True)

    # ------------------------------------------------------------- files
    @staticmethod
    def _results_path(project: ProjectDTO) -> Path:
        return Path(project.folder) / ANALYSIS_FOLDER / ANALYSIS_RESULTS_FILE

    @staticmethod
    def _read_results(path: Path) -> list[AnalysisRecordDTO]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [AnalysisRecordDTO.from_dict(item) for item in data.get("results", [])]
        except FileNotFoundError:
            return []
        except (OSError, ValueError, TypeError, AttributeError):
            logger.warning("Analysis results %s are not readable", path, exc_info=True)
            return []

    def _read_history(self) -> list[ProjectDTO]:
        try:
            data = json.loads(self._history_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError):
            logger.warning("Project history %s is not readable; starting a new one", self._history_path)
            return []
        items = data.get("projects", []) if isinstance(data, dict) else []
        projects = []
        for item in items:
            try:
                projects.append(ProjectDTO.from_dict(item))
            except (TypeError, KeyError):
                continue
        return projects

    def _write_history(self, projects: list[ProjectDTO]) -> None:
        _write_json(self._history_path, {"version": HISTORY_VERSION, "projects": [p.to_dict() for p in projects]})


def _same_place(old: Path, new: Path) -> bool:
    try:
        return new.exists() and os.path.samefile(old, new)
    except OSError:
        return False


def _write_json(path: Path, data: Any) -> None:
    """Write via a temporary file so a crash never leaves half a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)
