"""Sample points from a CSV table (e.g. a weather-station or well list), for IDW.

A CSV has a longitude and a latitude column (in degrees, WGS84) and value columns. The
coordinate columns are found by their names (lon / lng / longitude / x, lat / latitude / y,
any case, with or without units), or chosen by the user. The delimiter (comma, semicolon,
tab or pipe) and the encoding (UTF-8, with or without BOM, else Latin-1) are detected.
Rows without valid coordinates are skipped. The points come back as a point layer, the same
shape a point shapefile gives, so the IDW page treats both alike.
"""

from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass
from pathlib import Path

from backend.dto.vector_dto import POINT, VectorFeatureDTO, VectorFieldDTO, VectorLayerDTO
from backend.exceptions import InterpolationError

MAX_ROWS = 200_000

_LON = ("lon", "long", "lng", "longitude", "x", "xcoord", "x_coord", "lon_dd", "longitude_dd")
_LAT = ("lat", "latitude", "y", "ycoord", "y_coord", "lat_dd", "latitude_dd")


@dataclass(frozen=True)
class CsvTableDTO:
    """What a CSV offers: its columns, the numeric ones, and the coordinate columns guessed."""

    path: str
    columns: tuple[str, ...]
    numeric: tuple[str, ...]
    lon_column: str          # "" when none could be guessed
    lat_column: str
    rows: int


def inspect_csv(path: str) -> CsvTableDTO:
    header, rows = _read(path)
    numeric = tuple(name for i, name in enumerate(header) if _is_numeric_column(rows, i))
    lon, lat = guess_coordinate_columns(numeric)
    return CsvTableDTO(str(path), tuple(header), numeric, lon, lat, len(rows))


def guess_coordinate_columns(columns) -> tuple[str, str]:
    """The longitude and latitude columns among ``columns``, by name ("" when not found)."""
    def key(name: str) -> str:
        name = re.sub(r"\(.*?\)|\[.*?\]", "", name.lower())          # drop units: "Lat (deg)"
        return re.sub(r"[^a-z_]", "", name.strip().replace(" ", "_"))

    def find(names: tuple[str, ...]) -> str:
        for column in columns:              # exact names first
            if key(column) in names:
                return column
        for column in columns:              # then names that start with one, e.g. "longitude_wgs84"
            if any(key(column).startswith(n) for n in names if len(n) >= 3):
                return column
        return ""

    lon, lat = find(_LON), find(_LAT)
    return (lon, lat) if lon and lat and lon != lat else ("", "")


def read_point_csv(path: str, lon_column: str = "", lat_column: str = "") -> VectorLayerDTO:
    """The CSV's rows as points (WGS84), every column as an attribute."""
    file = Path(path)
    header, rows = _read(path)
    if not lon_column or not lat_column:
        lon_column, lat_column = guess_coordinate_columns(header)
    if not lon_column or not lat_column:
        raise InterpolationError("Choose the CSV's longitude and latitude columns (none is named lon/lat, "
                                 f"longitude/latitude or x/y). Its columns: {', '.join(header)}.")
    for name in (lon_column, lat_column):
        if name not in header:
            raise InterpolationError(f"The CSV has no column {name!r}.")
    if lon_column == lat_column:
        raise InterpolationError("Longitude and latitude must be different columns.")
    lon_i, lat_i = header.index(lon_column), header.index(lat_column)
    numeric = {i for i in range(len(header)) if _is_numeric_column(rows, i)}
    fields = tuple(VectorFieldDTO(name, "number" if i in numeric else "text") for i, name in enumerate(header))

    features, skipped = [], 0
    out_of_range = 0
    west = south = math.inf
    east = north = -math.inf
    for row in rows:
        lon, lat = _number(_cell(row, lon_i)), _number(_cell(row, lat_i))
        if lon is None or lat is None:
            skipped += 1
            continue
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            out_of_range += 1
            continue
        attributes = {name: (_number(_cell(row, i)) if i in numeric else _cell(row, i))
                      for i, name in enumerate(header)}
        features.append(VectorFeatureDTO(POINT, (((lon, lat),),), attributes, (lon, lat, lon, lat)))
        west, south, east, north = min(west, lon), min(south, lat), max(east, lon), max(north, lat)
    if not features:
        if out_of_range:
            raise InterpolationError(f"{lon_column} / {lat_column} are not longitude / latitude in degrees "
                                     "(values beyond ±180 / ±90; projected metres are not supported). "
                                     "Convert them to WGS84 degrees first.")
        raise InterpolationError(f"No row of {file.name} has numeric {lon_column} and {lat_column}.")
    return VectorLayerDTO(path=str(file), name=file.stem, kind=POINT,
                          crs=f"EPSG:4326 (CSV: {lon_column}, {lat_column})", feature_count=len(features),
                          fields=fields, features=tuple(features), bounds=(west, south, east, north))


# ------------------------------------------------------------- reading
def _read(path: str) -> tuple[list[str], list[list[str]]]:
    file = Path(path)
    if not file.is_file():
        raise InterpolationError(f"The CSV is not there: {file}")
    raw = file.read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:20_000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    try:
        header = [name.strip() for name in next(reader)]
    except StopIteration:
        raise InterpolationError(f"{file.name} is empty.") from None
    if len(header) < 3:
        raise InterpolationError(f"{file.name} needs a longitude, a latitude and a value column "
                                 f"(it has {len(header)} column(s)).")
    header = [name or f"column {i + 1}" for i, name in enumerate(header)]
    rows = []
    for row in reader:
        if not any(cell.strip() for cell in row):
            continue
        rows.append([cell.strip() for cell in row])
        if len(rows) > MAX_ROWS:
            raise InterpolationError(f"{file.name} has more than {MAX_ROWS:,} rows, too many to interpolate.")
    if not rows:
        raise InterpolationError(f"{file.name} has a header but no rows.")
    return header, rows


def _cell(row: list[str], index: int) -> str:
    return row[index] if index < len(row) else ""


def _number(text: str):
    if text is None or text == "":
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _is_numeric_column(rows: list[list[str]], index: int) -> bool:
    seen = False
    for row in rows:
        cell = _cell(row, index)
        if cell == "" or cell.upper() in ("NA", "N/A", "NAN", "NULL", "-"):
            continue
        if _number(cell) is None:
            return False
        seen = True
    return seen
