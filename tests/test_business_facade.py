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
