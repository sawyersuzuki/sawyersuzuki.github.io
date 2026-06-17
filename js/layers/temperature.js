/**
 * Temperature layer — 2m temperature heatmap on the globe.
 *
 * Lazy-loaded: data/weather.json is only fetched the first time this layer
 * is shown. Colors are precomputed once and stored on each datum so Globe.gl
 * does zero computation on every subsequent render frame.
 *
 * Resolution: 10° grid (≈ 612 cells) — fine enough to read the pattern,
 * light enough for smooth 60 fps.
 */
(function () {
  'use strict';

  const GRID_STEP = 10; // degrees — subsampled from the 5° weather.json grid
  const CELL_HALF = GRID_STEP / 2;

  // Shared lazy promise — created only on first show(), shared with wind.js
  function ensureData() {
    window.__weatherDataPromise = window.__weatherDataPromise
      || fetch('./data/weather.json').then(r => r.json());
    return window.__weatherDataPromise;
  }

  // Interpolated colormap: cold blue → cyan → green → yellow → hot red
  // Precompute once per datum; never called again during rendering.
  function tempColor(t) {
    const stops = [
      [-40, [20,  40, 200]],
      [-20, [0,  100, 255]],
      [ -5, [0,  210, 255]],
      [ 10, [40, 230,  80]],
      [ 22, [255, 230,  0]],
      [ 30, [255, 100,  0]],
      [ 40, [180,   0,  0]],
    ];
    const alpha = 0.46;
    if (t <= stops[0][0])
      return `rgba(${stops[0][1]},${alpha})`;
    if (t >= stops[stops.length - 1][0])
      return `rgba(${stops[stops.length - 1][1]},${alpha})`;
    for (let i = 0; i < stops.length - 1; i++) {
      const [t0, c0] = stops[i];
      const [t1, c1] = stops[i + 1];
      if (t >= t0 && t <= t1) {
        const f = (t - t0) / (t1 - t0);
        const r = Math.round(c0[0] + f * (c1[0] - c0[0]));
        const g = Math.round(c0[1] + f * (c1[1] - c0[1]));
        const b = Math.round(c0[2] + f * (c1[2] - c0[2]));
        return `rgba(${r},${g},${b},${alpha})`;
      }
    }
  }

  window.temperatureLayer = {
    active:       false,
    _globe:       null,
    _loaded:      false,

    init(globe) {
      this._globe = globe;
      // No fetch here — wait until the user actually toggles the layer.
    },

    _load() {
      if (this._loaded) return;
      this._loaded = true;

      ensureData().then(data => {
        // Subsample to GRID_STEP resolution; precompute color strings.
        const cells = data
          .filter(d => d.lat % GRID_STEP === 0 && d.lon % GRID_STEP === 0)
          .map(d => ({
            color:   tempColor(d.t),   // computed once, reused every frame
            polygon: [[
              [d.lon - CELL_HALF, d.lat - CELL_HALF],
              [d.lon + CELL_HALF, d.lat - CELL_HALF],
              [d.lon + CELL_HALF, d.lat + CELL_HALF],
              [d.lon - CELL_HALF, d.lat + CELL_HALF],
              [d.lon - CELL_HALF, d.lat - CELL_HALF],
            ]],
          }));
        this._globe.__tempCells = cells;
        if (this.active) this._apply();
      });
    },

    _apply() {
      this._globe
        .polygonsData(this._globe.__tempCells)
        .polygonGeoJsonGeometry(d => ({ type: 'Polygon', coordinates: d.polygon }))
        .polygonCapColor(d => d.color)   // simple property lookup — zero CPU cost
        .polygonSideColor(() => 'transparent')
        .polygonStrokeColor(() => false)
        .polygonAltitude(0.001);
    },

    show() {
      this.active = true;
      this._load();
      if (this._globe.__tempCells) this._apply();
    },

    hide() {
      this.active = false;
      this._globe.polygonsData([]);
    },

    toggle() {
      this.active ? this.hide() : this.show();
    },
  };
})();
