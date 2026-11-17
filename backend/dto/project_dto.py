"""Class diagram: ProjectDTO. A project is a folder holding everything the user does in it:

    <location>/<name>/
        project.json          the project's id, name and when it was created
        downloads/            datasets downloaded while the project is open
        analysis/             analysis results saved in the project
            analysis_results.json   every analysis run in the project (metrics, settings, file)
        explanation/          AI explanations of the analysis results (Markdown)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PROJECT_FILE = "project.json"
DOWNLOADS_FOLDER = "downloads"
ANALYSIS_FOLDER = "analysis"
EXPLANATION_FOLDER = "explanation"
ANALYSIS_RESULTS_FILE = "analysis_results.json"


@dataclass(frozen=True)
class ProjectDTO:
    id: str
    name: str
    folder: str                    # absolute path of the project folder
    owner_id: str = ""             # the user who created or last opened it on this computer
    created_at: str = ""           # ISO timestamps
    last_opened_at: str = ""

    @property
    def location(self) -> str:
        """The folder the project folder is in."""
        return str(Path(self.folder).parent)

    @property
    def downloads_dir(self) -> str:
        return str(Path(self.folder) / DOWNLOADS_FOLDER)

    @property
    def analysis_dir(self) -> str:
        return str(Path(self.folder) / ANALYSIS_FOLDER)

    @property
    def explanation_dir(self) -> str:
        return str(Path(self.folder) / EXPLANATION_FOLDER)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectDTO":
        values = {key: data[key] for key in cls.__dataclass_fields__ if key in data}
        return cls(**{key: str(value) for key, value in values.items()})


@dataclass(frozen=True)
class AnalysisRecordDTO:
    """One analysis run in a project, as kept in ``analysis_results.json``."""

    id: str
    category: str
    processes: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    output_path: str = ""          # relative to the project folder when inside it
    saved: bool = False            # False: the GeoTIFF was temporary (only the numbers are kept)
    dataset: str = ""              # the GeoTIFF analysed
    created_at: str = ""
    device: str = ""
    seconds: float = 0.0
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_result(cls, result, project: ProjectDTO) -> "AnalysisRecordDTO":
        """The record of a ResultDTO, with paths inside the project made relative to it."""
        return cls(
            id=result.id,
            category=result.category,
            processes=list(result.processes),
            metrics={key: float(value) for key, value in result.metrics.items()},
            output_path=relative_to_project(result.output_path, project) if result.saved else "",
            saved=bool(result.saved),
            dataset=relative_to_project(result.dataset.path, project) if result.dataset else "",
            created_at=result.created_at,
            device=result.device,
            seconds=float(result.seconds),
            notes=list(result.notes),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnalysisRecordDTO":
        values = {key: data[key] for key in cls.__dataclass_fields__ if key in data}
        return cls(**values)


def relative_to_project(path: str, project: ProjectDTO) -> str:
    """``path`` relative to the project folder (so it survives moving the project), else unchanged."""
    if not path:
        return ""
    try:
        return Path(path).resolve().relative_to(Path(project.folder).resolve()).as_posix()
    except ValueError:
        return path
