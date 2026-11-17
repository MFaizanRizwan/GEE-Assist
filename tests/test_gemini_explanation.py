"""GeminiClient.generate_explanation: the GeoTIFF, previews and prompt sent to Gemini (no network)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors

from backend.data.clients.gemini_client import NO_GEOTIFF_NOTE, GeminiClient
from backend.data.clients.prompts import EXPLANATION_SYSTEM_PROMPT
from backend.data.data_facade import DataFacade
from backend.dto.explanation_dto import ExplanationRequestDTO, LayerInfoDTO
from backend.dto.result_dto import ResultDTO
from backend.exceptions import LLMServiceError


class FakeFiles:
    def __init__(self, upload_error: Exception | None = None, states=("ACTIVE",)):
        self.upload_error, self.states = upload_error, list(states)
        self.uploads, self.deleted, self.gets = [], [], 0

    def upload(self, *, file, config):
        self.uploads.append({"file": file, "config": config})
        if self.upload_error:
            raise self.upload_error
        return SimpleNamespace(name="files/abc", state=SimpleNamespace(name=self.states.pop(0)))

    def get(self, *, name):
        self.gets += 1
        return SimpleNamespace(name=name, state=SimpleNamespace(name=self.states.pop(0)))

    def delete(self, *, name):
        self.deleted.append(name)


class FakeModels:
    def __init__(self, errors=()):
        self.errors, self.calls = list(errors), []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.errors:
            raise self.errors.pop(0)
        return SimpleNamespace(text="## Summary\nVegetation is healthy.")


def make_client(files=None, models=None):
    files, models = files or FakeFiles(), models or FakeModels()
    client = GeminiClient(api_key="unused", model="gemini-test", client=SimpleNamespace(models=models, files=files),
                          fallback_models=(), sleep=lambda _seconds: None)
    return client, files, models


@pytest.fixture
def request_for(tmp_path):
    def build(previews=(b"\x89PNG-one", b"\x89PNG-two")) -> ExplanationRequestDTO:
        tif = tmp_path / "result.tif"
        tif.write_bytes(b"II*\x00 fake tiff")
        result = ResultDTO("r1", "Vegetation", ["NDVI", "EVI"], {"NDVI mean": 0.4}, str(tif), saved=True)
        return ExplanationRequestDTO(result, "Vegetation", "Vegetation",
                                     layers=(LayerInfoDTO("NDVI", "NDVI"), LayerInfoDTO("EVI", "EVI")),
                                     previews=previews)
    return build


def unsupported_mime() -> Exception:
    message = "Unsupported MIME type: image/tiff"
    return genai_errors.ClientError(400, {"error": {"code": 400, "message": message, "status": "INVALID_ARGUMENT"}})


def test_the_geotiff_previews_and_prompt_are_sent_together(request_for):
    client, files, models = make_client()
    request = request_for()
    explanation = client.generate_explanation(request)

    upload = files.uploads[0]
    assert upload["file"] == request.tif_path
    assert upload["config"].mime_type == "image/tiff" and upload["config"].display_name == "result.tif"
    uploaded, first, second, prompt = models.calls[0]["contents"]
    assert uploaded.name == "files/abc"
    assert (first.inline_data.mime_type, first.inline_data.data) == ("image/png", b"\x89PNG-one")
    assert second.inline_data.data == b"\x89PNG-two"
    assert "# Metadata after the analysis (the result GeoTIFF)" in prompt
    assert models.calls[0]["config"].system_instruction == EXPLANATION_SYSTEM_PROMPT
    assert explanation.text.startswith("## Summary") and explanation.tif_attached
    assert explanation.model == "gemini-test" and explanation.request is request
    assert files.deleted == ["files/abc"]  # not left on Gemini's servers


def test_an_upload_still_processing_is_waited_for(request_for):
    client, files, models = make_client(files=FakeFiles(states=("PROCESSING", "PROCESSING", "ACTIVE")))
    assert client.generate_explanation(request_for()).tif_attached
    assert files.gets == 2 and len(models.calls) == 1


def test_a_refused_geotiff_is_dropped_and_the_previews_still_explained(request_for):
    client, files, models = make_client(models=FakeModels(errors=[unsupported_mime()]))
    explanation = client.generate_explanation(request_for())

    assert len(models.calls) == 2
    retry = models.calls[1]["contents"]
    assert len(retry) == 3 and retry[-1].endswith(NO_GEOTIFF_NOTE)
    assert explanation.text and not explanation.tif_attached
    assert files.deleted == ["files/abc"]


def test_a_geotiff_the_upload_refuses_is_skipped(request_for):
    client, files, models = make_client(files=FakeFiles(upload_error=unsupported_mime()))
    explanation = client.generate_explanation(request_for())
    assert not explanation.tif_attached and len(models.calls) == 1
    assert models.calls[0]["contents"][-1].endswith(NO_GEOTIFF_NOTE)
    assert files.deleted == []


def test_other_upload_errors_reach_the_user_as_plain_messages(request_for):
    error = genai_errors.ClientError(403, {"error": {"code": 403, "message": "API key not valid",
                                                      "status": "PERMISSION_DENIED"}})
    client, _, models = make_client(files=FakeFiles(upload_error=error))
    with pytest.raises(LLMServiceError, match="API key"):
        client.generate_explanation(request_for())
    assert models.calls == []


def test_the_upload_is_deleted_even_when_gemini_fails(request_for):
    busy = genai_errors.ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}})
    client, files, _ = make_client(models=FakeModels(errors=[busy] * 4))
    with pytest.raises(LLMServiceError, match="busy"):
        client.generate_explanation(request_for())
    assert files.deleted == ["files/abc"]


def test_a_missing_geotiff_is_reported(request_for):
    request = request_for()
    client, files, _ = make_client()
    Path(request.tif_path).unlink()
    with pytest.raises(LLMServiceError, match="no longer there"):
        client.generate_explanation(request)
    assert files.uploads == []


def test_data_facade_delegates_explanations_to_gemini(request_for):
    client, _, _ = make_client()
    assert DataFacade(gemini_client=client).generate_explanation(request_for()).text.startswith("## Summary")
