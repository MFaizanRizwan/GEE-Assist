"""A Leaflet map with layers stacked in a fixed order, for the IDW page.

Bottom to top: the world basemap, the interpolated surface, the boundaries (a polygon
shapefile) and the sample points; each can be shown or hidden. Ctrl+click on a boundary
asks for it to be selected or deselected (``feature_toggled``); the page keeps the
selection and sends it back (``set_selection``). The pointer over the surface is reported
(``pointer_moved``) so the page can show the value there.

Requires PyQt6-WebEngine; without it ``available`` is False and the page shows its own
picture instead. Calls made before the page has loaded are queued, and the map's state is
re-applied if the page reloads.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from PyQt6.QtCore import QFile, QIODevice, QObject, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from frontend.widgets.aoi_map_widget import WEB_ENGINE_AVAILABLE

if WEB_ENGINE_AVAILABLE:
    from PyQt6.QtWebChannel import QWebChannel
    from PyQt6.QtWebEngineCore import QWebEngineScript, QWebEngineSettings
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    from frontend.widgets.aoi_map_widget import _MapPage

MAP_HTML = Path(__file__).resolve().parents[1] / "resources" / "layer_map.html"
LAYERS = ("basemap", "surface", "boundaries", "points")

# Re-check Leaflet's size once the shown page has really been laid out, and only with a real size.
# Called synchronously as the view reappears, the page was still 0 x 0: with points or boundaries
# on the map, Leaflet then hung for good (the map froze while the rest of the app worked).
SAFE_RESIZE = ("setTimeout(function () { var el = document.getElementById('map');"
               " if (typeof map !== 'undefined' && el && el.clientWidth > 0 && el.clientHeight > 0)"
               " map.invalidateSize(false); }, 50);")


class _Bridge(QObject):
    ready = pyqtSignal()
    feature_toggled = pyqtSignal(int)
    pointer_moved = pyqtSignal(float, float)
    pointer_left = pyqtSignal()

    @pyqtSlot()
    def mapReady(self) -> None:  # noqa: N802 (called from JS)
        self.ready.emit()

    @pyqtSlot(int)
    def featureToggled(self, index: int) -> None:  # noqa: N802
        self.feature_toggled.emit(index)

    @pyqtSlot(float, float)
    def pointerMoved(self, lon: float, lat: float) -> None:  # noqa: N802
        self.pointer_moved.emit(lon, lat)

    @pyqtSlot()
    def pointerLeft(self) -> None:  # noqa: N802
        self.pointer_left.emit()


class LayerMapWidget(QWidget):
    feature_toggled = pyqtSignal(int)          # Ctrl+click on boundary feature ``index``
    pointer_moved = pyqtSignal(float, float)   # lon, lat over the surface
    pointer_left = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._ready = False
        self._pending: list[str] = []
        self._state: dict[str, str] = {}      # the last script of each kind, re-run if the page reloads
        self.sent: list[str] = []             # every script sent (for tests)
        self.reloads = 0                      # times the page was reloaded after its process died
        self._view = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if not WEB_ENGINE_AVAILABLE:
            layout.addWidget(QLabel("The world map needs PyQt6-WebEngine."))
            return
        self._bridge = _Bridge(self)
        self._bridge.ready.connect(self._on_ready)
        self._bridge.feature_toggled.connect(self.feature_toggled)
        self._bridge.pointer_moved.connect(self.pointer_moved)
        self._bridge.pointer_left.connect(self.pointer_left)
        self._channel = QWebChannel(self)
        self._channel.registerObject("bridge", self._bridge)
        self._view = QWebEngineView(self)
        self._view.setPage(_MapPage(self._view))
        self._view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        self._inject_webchannel()
        self._view.page().setWebChannel(self._channel)
        # If Chromium's page process crashes or is killed (it can, under memory pressure), the map
        # froze while the rest of the app went on: load it again; ``_on_ready`` restores its state.
        self._view.page().renderProcessTerminated.connect(self._on_page_died)
        self._view.load(QUrl.fromLocalFile(str(MAP_HTML)))
        layout.addWidget(self._view)

    @property
    def available(self) -> bool:
        return self._view is not None

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt API) - the wheel zooms the map, never the page
        event.accept()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().showEvent(event)
        self._run(SAFE_RESIZE, remember=None)

    # ------------------------------------------------------------- layers
    def set_basemap(self, name: str) -> None:
        """"streets" or "satellite"."""
        self._run(f"setBasemap({json.dumps(name)})", remember="basemap")

    def set_surface(self, png: bytes, bounds: tuple[float, float, float, float], opacity: float = 0.85) -> None:
        url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        west, south, east, north = bounds
        self._run(f"setSurface({json.dumps(url)}, {west}, {south}, {east}, {north}, {opacity})", remember="surface")

    def clear_surface(self) -> None:
        self._run("clearSurface()", remember="surface")

    def set_surface_opacity(self, opacity: float) -> None:
        self._run(f"setSurfaceOpacity({max(0.0, min(1.0, opacity))})", remember="opacity")

    def set_boundaries(self, geojson: str) -> None:
        """A FeatureCollection whose features carry ``properties.index`` (and ``name``); "" removes them."""
        self._run(f"setBoundaries({json.dumps(geojson)})", remember="boundaries")
        self._state.pop("selection", None)

    def set_selection(self, indices) -> None:
        self._run(f"setSelection({json.dumps(sorted(int(i) for i in indices))})", remember="selection")

    def set_other_areas_visible(self, on: bool) -> None:
        """Draw the boundaries of the areas not selected (off: only the selected area's outline)."""
        self._run(f"setOtherAreasVisible({'true' if on else 'false'})", remember="others")

    def set_boundary_style(self, filled: bool, colour: str = "#2E7D32", opacity: float = 0.55) -> None:
        """Outlines only, or every area filled in one colour (a single-colour map of the layer)."""
        opacity = max(0.0, min(1.0, float(opacity)))
        self._run(f"setBoundaryStyle({'true' if filled else 'false'}, {json.dumps(colour)}, {opacity})",
                  remember="boundary_style")

    def set_points(self, points) -> None:
        """[(lon, lat, label), ...]. The same points again are not re-sent: rebuilding thousands of
        markers on every selection change blocked the map for seconds."""
        data = [[float(lon), float(lat), str(label)] for lon, lat, label in points]
        script = f"setPoints({json.dumps(data)})"
        if self._state.get("points") == script:
            return
        self._run(script, remember="points")

    def set_layer_visible(self, name: str, on: bool) -> None:
        if name not in LAYERS:
            raise ValueError(f"Unknown layer {name!r}")
        self._run(f"setVisible({json.dumps(name)}, {'true' if on else 'false'})", remember=f"visible:{name}")

    def fit(self, bounds: tuple[float, float, float, float]) -> None:
        west, south, east, north = bounds
        self._run(f"fitTo({west}, {south}, {east}, {north})", remember="view")

    # ------------------------------------------------------------- internals
    def _run(self, script: str, remember: str | None) -> None:
        self.sent.append(script)
        if remember:
            self._state[remember] = script
        if self._view is None:
            return
        if self._ready:
            self._view.page().runJavaScript(script)
        else:
            self._pending.append(script)

    def _on_ready(self) -> None:
        """The page (re)loaded: re-apply the state in drawing order, then anything still queued."""
        self._ready = True
        order = ["basemap", "surface", "opacity", "boundaries", "boundary_style", "selection", "others",
                 "points"] + \
            [f"visible:{name}" for name in LAYERS] + ["view"]
        scripts = [self._state[key] for key in order if key in self._state]
        scripts += [s for s in self._pending if s not in scripts]
        for script in scripts:
            self._view.page().runJavaScript(script)
        self._pending.clear()

    def _on_page_died(self, *_args) -> None:
        """The page process ended or hung: reload the map (its state comes back on ``ready``)."""
        self._ready = False
        self.reloads += 1
        self._view.load(QUrl.fromLocalFile(str(MAP_HTML)))

    def _inject_webchannel(self) -> None:
        source = QFile(":/qtwebchannel/qwebchannel.js")
        if not source.open(QIODevice.OpenModeFlag.ReadOnly):
            return
        script = QWebEngineScript()
        script.setName("qwebchannel")
        script.setSourceCode(bytes(source.readAll()).decode("utf-8"))
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        self._view.page().scripts().insert(script)
        source.close()


def boundaries_geojson(layer, label_field: str = "") -> str:
    """A polygon layer (VectorLayerDTO) as GeoJSON for ``set_boundaries``: each feature's index
    in the layer and its name (from ``label_field``) in its properties."""
    features = []
    for index, feature in enumerate(layer.features):
        rings = [[list(map(float, point)) for point in ring] for ring in feature.parts if ring]
        if not rings:
            continue
        if feature.kind == "polygon":
            geometry = {"type": "MultiPolygon", "coordinates": _polygons(rings)}
        elif feature.kind == "polyline":
            geometry = {"type": "MultiLineString", "coordinates": rings}
        else:
            geometry = {"type": "MultiPoint", "coordinates": [p for ring in rings for p in ring]}
        features.append({"type": "Feature", "geometry": geometry,
                         "properties": {"index": index, "name": area_label(layer, index, label_field)}})
    return json.dumps({"type": "FeatureCollection", "features": features})


def _clockwise(ring) -> bool:
    area = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        area += x0 * y1 - x1 * y0
    return area < 0


def _polygons(rings) -> list:
    """Shapefile rings as GeoJSON polygons: each clockwise ring starts a polygon (an island),
    the anticlockwise rings after it are its holes."""
    polygons: list = []
    for ring in rings:
        if not polygons or _clockwise(ring):
            polygons.append([ring])
        else:
            polygons[-1].append(ring)
    return polygons


def polygons_of(layer, indices) -> tuple:
    """The chosen features' polygons as nested tuples (for IDWParamsDTO.boundary)."""
    out = []
    for index in sorted(indices):
        feature = layer.features[index]
        if feature.kind != "polygon":
            continue
        rings = [[tuple(map(float, p)) for p in ring] for ring in feature.parts if len(ring) >= 3]
        for polygon in _polygons(rings):
            out.append(tuple(tuple(ring) for ring in polygon))
    return tuple(out)


def _level(name: str) -> int:
    """The admin level in a field name (NAME_3 -> 3, ADM2_NAME -> 2), else -1."""
    import re

    found = re.findall(r"(\d+)", name)
    return int(found[-1]) if found else -1


def _name_like(name: str) -> bool:
    lowered = name.lower()
    return "name" in lowered and not lowered.startswith(("nl_", "var", "alt", "name_iso", "name_fao"))         or lowered in ("city", "district", "tehsil", "village", "title")


def _distinct_share(layer, field: str) -> float:
    values = [layer.features[i].attributes.get(field) for i in range(len(layer.features))]
    values = [str(v).strip() for v in values if v not in (None, "")]
    return len(set(values)) / max(1, len(layer.features))


def label_field_of(layer) -> str:
    """The attribute that names the areas best: the one that tells them apart (most distinct
    values), preferring name fields and, among those, the most detailed level (NAME_3 over
    NAME_1). A type column such as ENGTYPE_3 ("District" everywhere) is never chosen."""
    text = [f.name for f in layer.fields if f.type == "text"] or [f.name for f in layer.fields]
    if not text:
        return ""

    def score(name: str):
        return (round(_distinct_share(layer, name), 2) + (1.0 if _name_like(name) else 0.0), _level(name))

    return max(text, key=score)


def parent_fields_of(layer, field: str) -> list[str]:
    """Name fields of the regions containing an area, nearest first (NAME_3 -> NAME_2, NAME_1)."""
    level = _level(field)
    parents = [f.name for f in layer.fields if f.type == "text" and _name_like(f.name)
               and 0 < _level(f.name) < level and not f.name.lower().startswith(("nl_", "var"))]
    return sorted(parents, key=_level, reverse=True)


def area_label(layer, index: int, field: str) -> str:
    """What to call area ``index``: its ``field`` value; if that does not tell the areas apart
    (e.g. a type such as "District"), followed by the field that does; then the regions it lies in
    ("Lahore — Lahore, Punjab")."""
    attributes = layer.features[index].attributes
    value = attributes.get(field) if field else None
    text = "" if value in (None, "") else str(value)
    best = label_field_of(layer)
    if field and best != field and _distinct_share(layer, field) < 0.9:
        named = attributes.get(best)
        if named not in (None, ""):
            text = f"{text} · {named}" if text else str(named)
    if not text:
        text = f"Area {index + 1}"
    context: list[str] = []
    for parent in parent_fields_of(layer, best if best else field):
        value = attributes.get(parent)
        if value not in (None, "") and str(value) not in context:   # "Azad Kashmir, Azad Kashmir" -> once
            context.append(str(value))
    if context:
        text += " — " + ", ".join(context)
    return text
