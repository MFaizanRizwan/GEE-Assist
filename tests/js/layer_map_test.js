// Runs frontend/resources/layer_map.html's script against a stand-in Leaflet (setStyle merges, as
// Leaflet's does) and checks: Ctrl+click selects, the selection is highlighted, layers hide, and
// the other areas hide and come back. Run by tests/test_layer_map_js.py (needs Node.js).
// A stand-in for Leaflet: just enough to run layer_map.html's script and watch what it does.
const fs = require('fs');
const calls = [];
function layerish(extra) {
  return Object.assign({ _on: {}, addTo(m) { m.layers.add(this); return this; }, on(ev, f) { this._on[ev] = f; return this; },
    bindTooltip() { return this; }, setStyle(s) { this.style = Object.assign({}, this.style, s); }, setOpacity(o) { this.opacity = o; },
    bringToBack() {}, getBounds() { return { contains: () => true }; } }, extra || {});
}
const fakeMap = { layers: new Set(), _on: {}, panes: {},
  setView() { return this; }, on(ev, f) { this._on[ev] = f; }, createPane(n) { this.panes[n] = { style: {} }; },
  getPane(n) { return this.panes[n]; }, hasLayer(l) { return this.layers.has(l); }, removeLayer(l) { this.layers.delete(l); },
  fitBounds(b) { calls.push(['fit', b]); }, attributionControl: { setPrefix() {} }, invalidateSize() {} };
global.L = {
  tileLayer: () => layerish(), map: () => fakeMap, control: { scale: () => ({ addTo() {} }) }, canvas: () => ({}),
  layerGroup: () => layerish({ items: [], clearLayers() { this.items = []; } }),
  imageOverlay: (url, b, o) => layerish({ url, o }),
  circleMarker: () => layerish({ addTo(g) { g.items.push(this); return this; } }),
  DomEvent: { stop() {} },
  geoJSON(data, opts) {
    const g = layerish({ children: [], eachLayer(f) { this.children.forEach(f); } });
    data.features.forEach(feature => { const l = layerish({ feature }); l.style = opts.style(feature); opts.onEachFeature(feature, l); g.children.push(l); });
    return g;
  }
};
global.document = { getElementById: () => ({}) };
global.qt = { webChannelTransport: {} };
const fakeBridge = { mapReady() { calls.push(['ready']); }, featureToggled(i) { calls.push(['toggled', i]); },
                 pointerMoved(x, y) { calls.push(['moved', x, y]); }, pointerLeft() { calls.push(['left']); } };
global.QWebChannel = function (t, cb) { cb({ objects: { bridge: fakeBridge } }); };
const html = fs.readFileSync(process.argv[2], 'utf8');
eval(html.match(/<script>\n([\s\S]*?)<\/script>\s*<\/body>/)[1] + `
  setBoundaries(JSON.stringify({type: 'FeatureCollection', features: [
     {type: 'Feature', properties: {index: 0, name: 'West'}, geometry: null},
     {type: 'Feature', properties: {index: 1, name: 'East'}, geometry: null}]}));
  var east = boundaries.children[1];
  east._on.click({ originalEvent: { ctrlKey: false } });            // a plain click: nothing
  east._on.click({ originalEvent: { ctrlKey: true } });             // Ctrl+click: asks Python
  setSelection([1]);
  global.result = { eastWeight: east.style.weight, westWeight: boundaries.children[0].style.weight,
                    boundariesShown: map.hasLayer(boundaries) };
  setVisible('boundaries', false); global.result.hiddenAfter = !map.hasLayer(boundaries);
  setSurface('data:x', 1, 2, 3, 4, 0.8); map._on.mousemove({ latlng: { lng: 2, lat: 3 } });
  setVisible('surface', false); map._on.mousemove({ latlng: { lng: 2, lat: 3 } });
  setPoints([[1, 2, "pH: 6.5"]]); global.result.points = points.items.length;
  setVisible("boundaries", true); setOtherAreasVisible(false);
  global.result.westHidden = boundaries.children[0].style.stroke === false;
  global.result.eastShown = boundaries.children[1].style.weight === 3;
  var before = calls.filter(c => c[0] === "toggled").length;
  boundaries.children[0]._on.click({ originalEvent: { ctrlKey: true } });
  global.result.hiddenIgnored = calls.filter(c => c[0] === "toggled").length === before;
  setOtherAreasVisible(true);
  global.result.westBack = boundaries.children[0].style.stroke === true && boundaries.children[0].style.weight === 1.2;
`);
const toggles = calls.filter(c => c[0] === 'toggled');
const ok = toggles.length === 1 && toggles[0][1] === 1 && result.eastWeight === 3 && result.westWeight === 1.2
  && result.boundariesShown && result.hiddenAfter && result.points === 1
  && result.westHidden && result.eastShown && result.hiddenIgnored && result.westBack && calls.some(c => c[0] === "moved") && calls[calls.length - 1][0] === 'left';
console.log(JSON.stringify({ toggles, result, last: calls[calls.length - 1] }));
console.log(ok ? 'MAP LOGIC OK' : 'MAP LOGIC FAILED');
process.exit(ok ? 0 : 1);
