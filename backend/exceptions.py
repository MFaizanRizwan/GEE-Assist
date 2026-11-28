"""Backend errors. The UI catches ``GeeAssistError`` and shows ``str(error)``."""


class GeeAssistError(Exception):
    """Base class for expected backend errors."""


class ValidationError(GeeAssistError):
    """User input is invalid (e.g. empty natural-language query, UC-02 5a)."""


class AOIImportError(GeeAssistError):
    """GeoJSON file is unsupported or invalid (UC-04 6a / 6b)."""


class LLMServiceError(GeeAssistError):
    """Gemini is not configured, failed, or returned an unusable answer (Interpret Query)."""


class GEEError(GeeAssistError):
    """Google Earth Engine is not set up, refused a request, or returned no data (Fetch Data)."""


class GEESetupError(GEEError):
    """Earth Engine cannot be used until the user fixes the setup (sign-in, project, API).

    Retrying does not help, so downloads stop at once with the message.
    """


class GEERequestTooHeavyError(GEEError):
    """Earth Engine ran out of memory or time computing a request.

    Sending the same request again does not help; a smaller one may. When even the
    smallest request fails, downloads stop at once so the user can make the request
    lighter (shorter date range, mosaic composite).
    """


class PlaceSearchError(GeeAssistError):
    """A city / region / country could not be looked up, or has no boundary to use as an AOI."""
class MapError(GeeAssistError):
    """A GeoTIFF cannot be shown: it is missing, unreadable, or has no bands for the chosen view."""


class AnalysisError(GeeAssistError):
    """An analysis cannot run: no dataset, a band it needs is missing, or the files cannot be read."""


class ProjectError(GeeAssistError):
    """A project cannot be created, opened, renamed or moved, or there is none open when one is needed.

    ``field`` names the form field the problem is about (``name`` or ``location``), when there is one.
    """

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.field = field


class VectorError(GeeAssistError):
    """A shapefile cannot be shown: it is missing, unreadable, has no geometry, or cannot be reprojected."""


class TerrainError(GeeAssistError):
    """A DEM cannot be used: it is missing, unreadable, has no elevation band, or a surface cannot be derived."""


class InterpolationError(GeeAssistError):
    """A surface cannot be interpolated: no sample points, no numeric field, or bad parameters."""


class UpdateError(GeeAssistError):
    """The app could not update itself: the download failed or was not a valid release, or the
    new version could not be put in place. The running app is left as it was."""

    def __init__(self, message: str, web_page: bool = False):
        super().__init__(message)
        self.web_page = web_page   # the link opens a web page: show it in the browser instead


class PredictionError(GeeAssistError):
    """A prediction cannot be made: too few dates, files that do not cover the same place, a
    missing band or labels, or every chosen algorithm failed."""


class CatalogError(GeeAssistError):
    """A dataset could not be fetched from a provider: the download failed, the file was empty,
    or Earth Engine returned no features for the area."""


class ExplanationError(GeeAssistError):
    """An analysis result cannot be explained: it is not saved in the project, or its files are missing."""


class ReportError(GeeAssistError):
    """A report cannot be made or exported: the explanation is missing, or a file cannot be written."""
