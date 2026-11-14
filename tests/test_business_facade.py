"""The business facade hands gkonsol's new operations to the right service."""

from unittest.mock import MagicMock

import pytest

from backend.business.facade import BusinessFacade
from backend.dto import FormDTO


@pytest.fixture
def services():
    return MagicMock(), MagicMock(), MagicMock()  # user, request, download


@pytest.fixture
def facade(services):
    user, request, download = services
    return BusinessFacade(user_service=user, request_service=request, download_service=download,
                          map_service=MagicMock())


def test_checking_a_form_does_not_keep_it(facade, services):
    _, request, _ = services
    form = FormDTO(dataset="sentinel2_sr")
    assert facade.check_form(form) is request.check_form.return_value
    request.check_form.assert_called_once_with(form)
    request.validate_form.assert_not_called()


def test_session_info_comes_from_the_user_service(facade, services):
    user, _, _ = services
    assert facade.get_session_info() is user.get_session_info.return_value


def test_earth_engine_checks_and_sign_in_go_to_the_download_service(facade, services):
    _, _, download = services
    stop = MagicMock()
    assert facade.check_gee_setup() is download.check_gee_setup.return_value
    assert facade.begin_gee_sign_in() is download.begin_gee_sign_in.return_value
    assert facade.complete_gee_sign_in(stop) is download.complete_gee_sign_in.return_value
    download.complete_gee_sign_in.assert_called_once_with(stop)
    facade.cancel_gee_sign_in()
    download.cancel_gee_sign_in.assert_called_once_with()


@pytest.mark.parametrize(("method", "args"), [
    ("update_user", ("user",)),
    ("change_password", ("u1", "NewPass123", "NewPass123", "OldPass123")),
    ("set_profile_photo", ("photo.png",)),
    ("get_profile_photo", ("u1",)),
    ("remove_profile_photo", ()),
    ("create_user", ("new user",)),
    ("delete_user", ("u2",)),
    ("find_user_by_email", ("a@example.com",)),
])
def test_account_management_goes_to_the_user_service(facade, services, method, args):
    user, _, _ = services
    assert getattr(facade, method)(*args) is getattr(user, method).return_value
    getattr(user, method).assert_called_once_with(*args)


# ------------------------------------------------------------- projects
def _project(folder="C:/work/MyProject"):
    from backend.dto.project_dto import ProjectDTO

    return ProjectDTO(id="p1", name="MyProject", folder=folder)


def test_downloads_need_an_open_project(facade, services):
    from backend.exceptions import ProjectError

    _, request, download = services
    request.get_current_project.return_value = None
    with pytest.raises(ProjectError, match="Create or open a project"):
        facade.start_download(FormDTO(dataset="sentinel2_sr"))
    download.start_download.assert_not_called()


def test_downloads_go_into_the_projects_downloads_folder(facade, services):
    _, request, download = services
    request.get_current_project.return_value = _project()
    facade.start_download(FormDTO(dataset="sentinel2_sr", output_dir="D:/somewhere/else"))
    sent = download.start_download.call_args.args[0]
    assert sent.output_dir == _project().downloads_dir


def test_renaming_moves_the_projects_downloads_along(facade, services):
    _, request, download = services
    request.get_current_project.return_value = _project()
    request.rename_project.return_value = _project("C:/work/Renamed")
    download.is_busy_in.return_value = False
    assert facade.rename_project("Renamed").folder == "C:/work/Renamed"
    download.relocate.assert_called_once_with("C:/work/MyProject", "C:/work/Renamed")


def test_a_running_download_blocks_moving_the_project(facade, services):
    from backend.exceptions import ProjectError

    _, request, download = services
    request.get_current_project.return_value = _project()
    download.is_busy_in.return_value = True
    with pytest.raises(ProjectError, match="download in this project is running"):
        facade.move_project("D:/new place")
    request.move_project.assert_not_called()


def test_projects_are_created_and_listed_for_the_signed_in_user(facade, services):
    user, request, _ = services
    user.current_user.id = "u1"
    facade.create_project("MyProject", "C:/work")
    request.create_project.assert_called_once_with("MyProject", "C:/work", "u1")
    facade.list_projects()
    request.list_projects.assert_called_once_with("u1")


def test_signing_out_closes_the_project(facade, services):
    user, request, _ = services
    facade.log_out()
    user.log_out.assert_called_once()
    request.close_project.assert_called_once()


def test_analysis_runs_are_recorded_in_the_project(services):
    _, request, download = services
    analysis = MagicMock()
    facade = BusinessFacade(user_service=services[0], request_service=request, download_service=download,
                            map_service=MagicMock(), analysis_service=analysis)
    request.get_current_project.return_value = _project()
    result = facade.run_analysis("dataset", "request")
    request.record_analysis_result.assert_called_once_with(result)
    saved = facade.save_analysis_result(result, "C:/work/MyProject/analysis/x.tif")
    request.record_analysis_result.assert_called_with(saved)

    request.get_current_project.return_value = None
    from backend.exceptions import ProjectError

    with pytest.raises(ProjectError):
        facade.run_analysis("dataset", "request")
