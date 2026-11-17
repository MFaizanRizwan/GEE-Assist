"""BusinessFacade: reports are made from, and kept in, the open project."""

from unittest.mock import MagicMock

import pytest

from backend.business.facade import BusinessFacade
from backend.dto.project_dto import ProjectDTO
from backend.exceptions import ProjectError, ReportError

PROJECT = ProjectDTO("p1", "Project 1", "C:/work/Project 1")


@pytest.fixture
def services():
    request, reports = MagicMock(), MagicMock()
    request.get_current_project.return_value = PROJECT
    return request, reports


@pytest.fixture
def facade(services):
    request, reports = services
    return BusinessFacade(user_service=MagicMock(), request_service=request, download_service=MagicMock(),
                          map_service=MagicMock(), report_service=reports)


def test_explanations_come_from_the_open_project(facade, services):
    assert facade.list_explanations() is services[1].list_explanations.return_value
    services[1].list_explanations.assert_called_once_with(PROJECT)


def test_no_project_no_explanations(facade, services):
    services[0].get_current_project.return_value = None
    assert facade.list_explanations() == []
    services[1].list_explanations.assert_not_called()


def test_a_report_is_built_and_kept_in_the_open_project(facade, services):
    assert facade.build_report("x_explanation.md") is services[1].build_report.return_value
    services[1].build_report.assert_called_once_with("x_explanation.md", PROJECT)
    assert facade.save_report("report", b"%PDF") is services[1].save_report.return_value
    services[1].save_report.assert_called_once_with("report", b"%PDF", PROJECT)


@pytest.mark.parametrize(("method", "args"), [("build_report", ("x.md",)), ("save_report", ("report", b"%PDF"))])
def test_reports_need_an_open_project(facade, services, method, args):
    services[0].get_current_project.return_value = None
    with pytest.raises(ProjectError, match="Create or open a project"):
        getattr(facade, method)(*args)


def test_exporting_goes_to_the_report_service(facade, services):
    assert facade.export_report("a.pdf", "D:/b.pdf") is services[1].export_report.return_value
    services[1].export_report.assert_called_once_with("a.pdf", "D:/b.pdf")


def test_a_build_without_reports_says_so(services):
    facade = BusinessFacade(user_service=MagicMock(), request_service=services[0], download_service=MagicMock(),
                            map_service=MagicMock())
    with pytest.raises(ReportError, match="not set up"):
        facade.build_report("x.md")
