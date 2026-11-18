"""IGeminiClient implementation using the ``google-genai`` SDK."""

from __future__ import annotations

import json
import logging
import time
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

from backend.data.clients.i_gemini_client import IGeminiClient
from backend.config.llm import FALLBACK_MODELS
from backend.data.clients.prompts import (
    EXPLANATION_SYSTEM_PROMPT,
    build_explanation_prompt,
    build_query_system_prompt,
)
from backend.dto import FormDTO
from backend.dto.explanation_dto import ExplanationDTO, ExplanationRequestDTO
from backend.exceptions import LLMServiceError

log = logging.getLogger(__name__)


class QueryInterpretation(BaseModel):
    """JSON schema Gemini must answer with (structured output)."""

    dataset: str = ""
    bands: list[str] = Field(default_factory=list)
    start_date: str = ""
    end_date: str = ""
    aoi_name: str = ""
    aoi_bbox: list[float] = Field(default_factory=list)
    max_cloud_cover: int = -1
    scale_m: int = 0
    composite: str = ""
    analysis_type: str = ""
    processes: list[str] = Field(default_factory=list)
    clarification: str = ""


def bbox_to_geojson(bbox: list[float]) -> str:
    min_lon, min_lat, max_lon, max_lat = (float(v) for v in bbox)
    ring = [[min_lon, min_lat], [max_lon, min_lat], [max_lon, max_lat], [min_lon, max_lat], [min_lon, min_lat]]
    return json.dumps({"type": "Polygon", "coordinates": [ring]})


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value.strip()[:10]) if value and value.strip() else None
    except ValueError:
        return None


def interpretation_to_form(data: QueryInterpretation, query: str) -> FormDTO:
    """Map Gemini's answer onto a FormDTO (no catalogue checks here)."""
    aoi = ""
    if len(data.aoi_bbox) == 4:
        try:
            aoi = bbox_to_geojson(data.aoi_bbox)
        except (TypeError, ValueError):
            aoi = ""
    return FormDTO(
        dataset=data.dataset.strip(),
        bands=[b.strip() for b in data.bands if b.strip()],
        scale=data.scale_m if data.scale_m > 0 else None,
        max_cloud_cover=data.max_cloud_cover if 0 <= data.max_cloud_cover <= 100 else None,
        composite=data.composite.strip(),
        aoi=aoi,
        aoi_name=data.aoi_name.strip(),
        start_date=_parse_date(data.start_date),
        end_date=_parse_date(data.end_date),
        analysis_type=data.analysis_type.strip(),
        processes=[p.strip() for p in data.processes if p.strip()],
        source="nl",
        query_text=query,
        clarification=data.clarification.strip(),
    )


class GeminiClient(IGeminiClient):
    def __init__(self, api_key: str, model: str, client=None, fallback_models=FALLBACK_MODELS, sleep=time.sleep):
        """``client`` lets tests pass a fake ``genai.Client``; ``sleep`` lets them skip the waits."""
        self._api_key = api_key
        # Try the configured model first, then current fallbacks (no duplicates, order kept).
        self._models = list(dict.fromkeys([model, *fallback_models]))
        self._client = client
        self._sleep = sleep

    def set_api_key(self, api_key: str) -> None:
        api_key = api_key.strip()
        if api_key != self._api_key:
            self._api_key = api_key
            self._client = None  # the next request makes a client with the new key

    def process_query(self, prompt: str) -> FormDTO:
        raw = self._generate(prompt, build_query_system_prompt(), temperature=0.0,
                             response_mime_type="application/json", response_schema=QueryInterpretation)
        try:
            data = QueryInterpretation.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning("Unusable Gemini answer: %s", raw[:500])
            raise LLMServiceError("Gemini's answer couldn't be read. Please try again.") from exc
        return interpretation_to_form(data, prompt)

    def generate_explanation(self, request: ExplanationRequestDTO) -> ExplanationDTO:
        """Send the saved result GeoTIFF, a PNG preview of each layer and the prompt to Gemini.

        Gemini may refuse an attachment (it does not read GeoTIFFs, and often answers only
        "400 INVALID_ARGUMENT"). Then the request is sent again with less: without the GeoTIFF,
        then without the previews, so the explanation is at least made from the metadata.
        """
        sdk = self._sdk()
        from google.genai import types

        prompt = build_explanation_prompt(request)
        previews = [types.Part.from_bytes(data=png, mime_type="image/png") for png in request.previews]
        uploaded = self._upload_geotiff(sdk, request.tif_path)
        # (contents, GeoTIFF sent, previews sent), from the most to the least attached
        attempts = []
        if uploaded is not None:
            attempts.append(([uploaded, *previews, prompt], True, bool(previews)))
        if previews:
            attempts.append(([*previews, prompt + NO_GEOTIFF_NOTE], False, True))
        attempts.append(([prompt + NO_ATTACHMENTS_NOTE], False, False))
        try:
            for contents, tif_sent, previews_sent in attempts:
                attached = len(contents) > 1
                try:
                    text = self._generate(contents, EXPLANATION_SYSTEM_PROMPT, attachments=attached,
                                          temperature=EXPLANATION_TEMPERATURE)
                except _UnsupportedFile:
                    log.warning("Gemini refused the attachments (GeoTIFF: %s, previews: %s); sending less",
                                tif_sent, previews_sent)
                    continue
                return ExplanationDTO(text=text, model=self._models[0], tif_attached=tif_sent,
                                      previews_attached=previews_sent, request=request)
            raise LLMServiceError(USER_MESSAGES["other"])  # unreachable: the last attempt has no attachments
        finally:
            if uploaded is not None:
                self._delete_upload(sdk, uploaded)

    # ------------------------------------------------------------------ internals
    def _sdk(self):
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise LLMServiceError("Gemini isn't set up yet. Enter your Gemini API key in Options → Settings…")
        try:
            from google import genai
        except ImportError as exc:
            raise LLMServiceError("Gemini support isn't installed. Run: pip install -r requirements.txt") from exc
        self._client = genai.Client(api_key=self._api_key)
        return self._client

    def _upload_geotiff(self, sdk, path: str):
        """The GeoTIFF uploaded through the Files API (it may be larger than an inline request
        allows), or None when Gemini does not take it (too large, or a file type it refuses)."""
        file = Path(path)
        if not file.is_file():
            raise LLMServiceError("The result GeoTIFF is no longer there. Run the analysis again.")
        if file.stat().st_size > MAX_UPLOAD_BYTES:
            log.warning("%s is larger than Gemini's file limit; explaining from the previews", file)
            return None
        from google.genai import types

        try:
            uploaded = sdk.files.upload(file=str(file), config=types.UploadFileConfig(
                mime_type=GEOTIFF_MIME_TYPE, display_name=file.name))
            waited = 0.0
            while _state(uploaded) == "PROCESSING" and waited < UPLOAD_WAIT_SEC:
                self._sleep(UPLOAD_POLL_SEC)
                waited += UPLOAD_POLL_SEC
                uploaded = sdk.files.get(name=uploaded.name)
        except Exception as exc:  # the full error goes to the log, never to the user
            kind = _classify(exc)
            log.warning("Uploading %s to Gemini failed (%s): %s", file.name, kind, exc)
            if kind == "file":
                return None
            raise LLMServiceError(USER_MESSAGES[kind]) from exc
        if _state(uploaded) not in ("ACTIVE", ""):
            log.warning("Gemini could not process %s (state %s)", file.name, _state(uploaded))
            self._delete_upload(sdk, uploaded)
            return None
        return uploaded

    @staticmethod
    def _delete_upload(sdk, uploaded) -> None:
        """Gemini deletes uploads after 48 hours anyway; delete it now, never failing over it."""
        try:
            sdk.files.delete(name=uploaded.name)
        except Exception:  # noqa: BLE001
            log.info("Could not delete the uploaded file %s", getattr(uploaded, "name", ""), exc_info=True)

    def _generate(self, contents, system_instruction: str, attachments: bool = False, **settings) -> str:
        """Call Gemini. A busy or retired model is skipped for the next one; if all are
        busy, wait briefly and try once more. Only a short, plain message reaches the user.

        With ``attachments`` (files or images in ``contents``), an invalid-argument answer means
        Gemini refused one of them: ``_UnsupportedFile`` is raised so the caller can send less."""
        sdk = self._sdk()
        from google.genai import types

        config = types.GenerateContentConfig(system_instruction=system_instruction, **settings)
        last_kind = "other"
        for round_number in range(RETRY_ROUNDS):
            if round_number:
                self._sleep(RETRY_WAIT_SEC)  # every model was busy: give Gemini a moment
            for model in list(self._models):
                try:
                    response = sdk.models.generate_content(model=model, contents=contents, config=config)
                except Exception as exc:  # the full error goes to the log, never to the user
                    last_kind = _classify(exc)
                    log.warning("Gemini %s failed (%s): %s", model, last_kind, exc)
                    if last_kind == "model":
                        self._models.remove(model)  # retired: don't try it again this session
                        continue
                    if last_kind in ("busy", "quota"):
                        continue  # overloaded, or this model's limit is used up: try the next one
                    if last_kind == "file" or (attachments and _is_invalid_argument(exc)):
                        raise _UnsupportedFile(USER_MESSAGES["file"]) from exc
                    raise LLMServiceError(USER_MESSAGES[last_kind]) from exc

                text = (getattr(response, "text", None) or "").strip()
                if not text:
                    raise LLMServiceError("Gemini didn't return an answer. Please rephrase and try again.")
                if model != self._models[0]:
                    reason = {"model": "is retired", "quota": "reached its usage limit"}.get(last_kind, "was busy")
                    log.warning("Gemini model %s %s; using %s for this session.", self._models[0], reason, model)
                    self._models.remove(model)
                    self._models.insert(0, model)
                return text
        raise LLMServiceError(USER_MESSAGES["model" if not self._models else last_kind])


# ----------------------------------------------------------------------------- explanation
EXPLANATION_TEMPERATURE = 0.3
GEOTIFF_MIME_TYPE = "image/tiff"
MAX_UPLOAD_BYTES = 2 * 1024 ** 3                # the Files API's limit per file
UPLOAD_POLL_SEC = 1.0                           # while Gemini is still processing an upload
UPLOAD_WAIT_SEC = 30.0
NO_GEOTIFF_NOTE = ("\n\nNote: the result GeoTIFF could not be attached (Gemini does not accept this file "
                   "type); explain from the previews and the metadata above.")


NO_ATTACHMENTS_NOTE = ("\n\nNote: Gemini could not take the attached GeoTIFF or previews; explain from the "
                       "metadata and numbers above, and say that the spatial patterns could not be seen.")


def _is_invalid_argument(exc: Exception) -> bool:
    """A 400 INVALID_ARGUMENT answer (Gemini often gives no other detail for a file it refuses)."""
    status = str(getattr(exc, "status", "") or "").upper()
    return getattr(exc, "code", None) == 400 or status == "INVALID_ARGUMENT"


def _state(uploaded) -> str:
    """An uploaded file's state: "PROCESSING", "ACTIVE", "FAILED" or "" when not given."""
    state = getattr(uploaded, "state", None)
    return str(getattr(state, "name", state) or "").upper()


class _UnsupportedFile(LLMServiceError):
    """Gemini refused an attached file (e.g. a file type it does not read)."""


# ----------------------------------------------------------------------------- error handling
# When every model is busy, wait this long and go through them once more.
RETRY_ROUNDS = 2
RETRY_WAIT_SEC = 2.0

USER_MESSAGES = {
    "key": "Gemini didn't accept the API key. Check it in Options → Settings…",
    "quota": "The Gemini usage limit has been reached. Please wait a minute and try again.",
    "busy": "Gemini is busy right now. Please try again in a moment.",
    "model": "The Gemini model is no longer available. Set a current model in GEMINI_MODEL in the .env file.",
    "network": "Can't reach Gemini. Check your internet connection and try again.",
    "other": "Gemini couldn't process the request. Please try again.",
    "file": "Gemini couldn't read the attached file.",
}


def _classify(exc: Exception) -> str:
    """Sort an SDK / network error into one of the USER_MESSAGES kinds."""
    code = getattr(exc, "code", None)
    status = str(getattr(exc, "status", "") or "").upper()
    text = str(exc).lower()
    if code in (401, 403) or status in ("UNAUTHENTICATED", "PERMISSION_DENIED") or "api key" in text or "api_key" in text:
        return "key"
    if (code == 400 or status == "INVALID_ARGUMENT") and any(word in text for word in ("mime", "unsupported")):
        return "file"
    if code == 429 or status == "RESOURCE_EXHAUSTED" or "quota" in text:
        return "quota"
    if code == 404 or status == "NOT_FOUND":
        return "model"
    if (isinstance(code, int) and code >= 500) or status in ("UNAVAILABLE", "INTERNAL", "DEADLINE_EXCEEDED"):
        return "busy"
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)) or any(
        word in text for word in ("getaddrinfo", "connection", "timed out", "timeout", "network")
    ):
        return "network"
    return "other"
