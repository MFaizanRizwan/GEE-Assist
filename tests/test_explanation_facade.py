"""BusinessFacade: the result GeoTIFF is saved in the project before it goes to Gemini."""

from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from backend.business.facade import BusinessFacade
from backend.business.facade.business_facade import free_path
from backend.dto.project_dto import ProjectDTO
from backend.dto.result_dto import ResultDTO
from backend.exceptions import ExplanationError, ProjectError


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "Project 1"
    (folder / "analysis").mkdir(parents=True)
    return ProjectDTO("p1", "Project 1", str(folder))


@pytest.fixture
def services(project):
    request, analysis, explanation = MagicMock(), MagicMock(), MagicMock()
    request.get_current_project.return_value = project
    analysis.save_result.side_effect = lambda result, path: replace(result, output_path=path, saved=True)
    return request, analysis, explanation


@pytest.fixture
def facade(services):
    request, analysis, explanation = services
    return BusinessFacade(user_service=MagicMock(), request_service=request, download_service=MagicMock(),
                          map_service=MagicMock(), analysis_service=analysis, explanation_service=explanation)


def unsaved(tmp_path) -> ResultDTO:
    return ResultDTO("r1", "Vegetation", ["NDVI"], output_path=str(tmp_path / "temp" / "result.tif"))


def test_an_unsaved_result_is_saved_in_the_project_before_it_is_explained(facade, services, project, tmp_path):
    request_service, analysis, explanation = services
    prepared = facade.prepare_explanation(unsaved(tmp_path))

    saved_path = analysis.save_result.call_args.args[1]
    assert saved_path == str(tmp_path / "Project 1" / "analysis" / "result.tif")
    sent = explanation.prepare.call_args.args[0]
    assert sent.saved and sent.output_path == saved_path
    request_service.record_analysis_result.assert_called_once()  # analysis_results.json has the saved file
    assert prepared is explanation.prepare.return_value


def test_an_earlier_result_with_the_same_name_is_not_overwritten(facade, services, project, tmp_path):
    (tmp_path / "Project 1" / "analysis" / "result.tif").write_bytes(b"earlier")
    facade.prepare_explanation(unsaved(tmp_path))
    assert services[1].save_result.call_args.args[1].endswith("result_2.tif")


def test_a_saved_result_is_not_saved_again(facade, services, tmp_path):
    result = replace(unsaved(tmp_path), saved=True)
    facade.prepare_explanation(result)
    services[1].save_result.assert_not_called()
    services[2].prepare.assert_called_once_with(result)


def test_explaining_needs_an_open_project(facade, services, tmp_path):
    services[0].get_current_project.return_value = None
    with pytest.raises(ProjectError, match="Create or open a project"):
        facade.prepare_explanation(unsaved(tmp_path))


def test_the_explanation_is_kept_in_the_projects_explanation_folder(facade, services, tmp_path):
    assert facade.explain_analysis_result("request") is services[2].explain.return_value
    services[2].explain.assert_called_once_with("request", str(tmp_path / "Project 1" / "explanation"))


def test_an_explanation_needs_an_open_project(facade, services):
    services[0].get_current_project.return_value = None
    with pytest.raises(ProjectError, match="explanation folder"):
        facade.explain_analysis_result("request")
    services[2].explain.assert_not_called()


def test_a_build_without_explanations_says_so(services, tmp_path):
    request, analysis, _ = services
    facade = BusinessFacade(user_service=MagicMock(), request_service=request, download_service=MagicMock(),
                            map_service=MagicMock(), analysis_service=analysis)
    with pytest.raises(ExplanationError):
        facade.explain_analysis_result("request")


def test_free_path_counts_up(tmp_path):
    (tmp_path / "a.tif").write_bytes(b"")
    (tmp_path / "a_2.tif").write_bytes(b"")
    assert free_path(tmp_path / "a.tif") == tmp_path / "a_3.tif"
    assert free_path(tmp_path / "b.tif") == tmp_path / "b.tif"
