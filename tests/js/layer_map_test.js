// Runs frontend/resources/layer_map.html's script against a stand-in Leaflet and checks:
// Ctrl+click selects an area (on the area, on a sample point inside it, or on the map),
// points stay above the boundaries on their shared canvas, layers hide and show, the areas
// not selected hide and come back, and pointer messages are sent at most once a frame
// ("left" only once). Run by tests/test_layer_map_js.py (needs Node.js).
const fs = require('fs');

const calls = [];
const drawOrder = [];                         // the shared canvas: shapes in the order they are drawn
function layerish(extra) {
  const layer = Object.assign({
    _on: {}, style: {},
    addTo(target) { target.add(this); return this; },
    on(ev, f) { this._on[ev] = f; return this; },
    bindTooltip() { return this; },
    setStyle(s) { this.style = Object.assign({}, this.style, s); },     // merges, as Leaflet's does
    setOpacity(o) { this.opacity = o; },
    bringToBack() {},
    bringToFront() { const i = drawOrder.indexOf(this); if (i >= 0) { drawOrder.splice(i, 1); drawOrder.push(this); } },
    getBounds() { return { contains: () => true }; },
  }, extra || {});
  return layer;
}
const fakeMap = {
  layers: new Set(), _on: {}, panes: {},
  add(layer) {
    this.layers.add(layer);
    (layer.children || layer.items || [layer]).forEach(child => { if (!drawOrder.includes(child)) drawOrder.push(child); });
  },
  setView() { return this; }, on(ev, f) { this._on[ev] = f; },
  createPane(n) { this.panes[n] = { style: {} }; }, getPane(n) { return this.panes[n]; },
  hasLayer(l) { return this.layers.has(l); }, removeLayer(l) { this.layers.delete(l); },
  fitBounds(b) { calls.push(['fit', b]); }, attributionControl: { setPrefix() {} }, invalidateSize() {},
};
global.L = {
  tileLayer: () => layerish(), map: () => fakeMap, control: { scale: () => ({ addTo() {} }) }, canvas: () => ({}),
  layerGroup: () => layerish({
    items: [], clearLayers() { this.items = []; },
    add(marker) { this.items.push(marker); if (fakeMap.hasLayer(this)) drawOrder.push(marker); },
    eachLayer(f) { this.items.forEach(f); },
  }),
  imageOverlay: (url, b, o) => layerish({ url, o }),
  circleMarker: (latlng) => layerish({ latlng, kind: 'point' }),
  DomEvent: { stop() {} },
  geoJSON(data, opts) {
    const group = layerish({ children: [], eachLayer(f) { this.children.forEach(f); } });
    data.features.forEach(feature => {
      const layer = layerish({ feature, kind: 'area' });
      layer.style = opts.style(feature);
      opts.onEachFeature(feature, layer);
      group.children.push(layer);
    });
    return group;
  },
};
global.document = { getElementById: () => ({}) };
global.qt = { webChannelTransport: {} };
const fakeBridge = {
  mapReady() { calls.push(['ready']); }, featureToggled(i) { calls.push(['toggled', i]); },
  pointerMoved(x, y) { calls.push(['moved', x, y]); }, pointerLeft() { calls.push(['left']); },
};
global.QWebChannel = function (t, cb) { cb({ objects: { bridge: fakeBridge } }); };

const html = fs.readFileSync(process.argv[2], 'utf8');
const square = (x0, y0, x1, y1) => ({ type: 'Polygon', coordinates: [[[x0, y0], [x0, y1], [x1, y1], [x1, y0], [x0, y0]]] });
const ctrl = (lng, lat) => ({ originalEvent: { ctrlKey: true }, latlng: { lng, lat } });
const plain = (lng, lat) => ({ originalEvent: { ctrlKey: false }, latlng: { lng, lat } });
const toggled = () => calls.filter(c => c[0] === 'toggled').map(c => c[1]);

eval(html.match(/<script>\n([\s\S]*?)<\/script>\s*<\/body>/)[1] + `
  var result = {};
  setPoints([[0.5, 0.5, 'pH: 6.5'], [1.5, 0.5, 'pH: 7.1']]);
  setBoundaries(JSON.stringify({ type: 'FeatureCollection', features: [
    { type: 'Feature', properties: { index: 0, name: 'West' }, geometry: ${JSON.stringify(square(0, 0, 1, 1))} },
    { type: 'Feature', properties: { index: 1, name: 'East' }, geometry: ${JSON.stringify(square(1, 0, 2, 1))} }] }));
  result.pointsOnTop = drawOrder[drawOrder.length - 1].kind === 'point' && drawOrder[drawOrder.length - 2].kind === 'point';
  var west = boundaries.children[0], east = boundaries.children[1];

  east._on.click(plain(1.5, 0.5));                    // a plain click: nothing
  east._on.click(ctrl(1.5, 0.5));                     // Ctrl+click on the area
  points.items[0]._on.click(ctrl(0.5, 0.5));          // Ctrl+click on a point inside West
  fakeMap._on.click(ctrl(1.8, 0.2));                  // Ctrl+click on the map, inside East
  fakeMap._on.click(ctrl(5, 5));                      // Ctrl+click outside every area: nothing
  result.toggles = toggled();

  setSelection([1]);
  result.eastWeight = east.style.weight; result.westWeight = west.style.weight;
  setOtherAreasVisible(false);
  result.westHidden = west.style.stroke === false && east.style.weight === 3;
  var before = toggled().length;
  west._on.click(ctrl(0.5, 0.5));
  points.items[0]._on.click(ctrl(0.5, 0.5));
  result.hiddenIgnored = toggled().length === before;
  setOtherAreasVisible(true);
  result.westBack = west.style.stroke === true && west.style.weight === 1.2;

  setVisible('boundaries', false); result.hidden = !fakeMap.hasLayer(boundaries);
  setVisible('boundaries', true);
  result.pointsStillOnTop = drawOrder[drawOrder.length - 1].kind === 'point';

  setSurface('data:x', 0, 0, 2, 1, 0.8);
  for (var i = 0; i < 50; i++) fakeMap._on.mousemove({ latlng: { lng: 1, lat: 0.5 } });
  global.check = function () {
    result.moves = calls.filter(c => c[0] === 'moved').length;
    for (var j = 0; j < 20; j++) { setVisible('surface', false); fakeMap._on.mousemove({ latlng: { lng: 1, lat: 0.5 } }); }
    setTimeout(function () {
      result.lefts = calls.filter(c => c[0] === 'left').length;
      var ok = result.pointsOnTop && JSON.stringify(result.toggles) === '[1,0,1]' && result.eastWeight === 3
        && result.westWeight === 1.2 && result.westHidden && result.hiddenIgnored && result.westBack && result.hidden
        && result.pointsStillOnTop && result.moves === 1 && result.lefts === 1;
      console.log(JSON.stringify(result));
      console.log(ok ? 'MAP LOGIC OK' : 'MAP LOGIC FAILED');
      process.exit(ok ? 0 : 1);
    }, 60);
  };
  setTimeout(global.check, 60);
`);
