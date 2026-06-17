/**
 * Temperature layer — 2m temperature heatmap on the globe.
 *
 * Data source: data/weather.json (Celsius, real Open-Meteo forecast data,
 * refreshed daily by the GitHub Action in .github/workflows/update-weather.yml).
 *
 * Color scale covers the full observed global surface range: -70°C → +50°C.
 * Colors are precomputed once on data load; Globe.gl accessors do zero
 * computation per render frame.
 *
 * Lazy-loaded: fetch only starts when the layer is first toggled.
 */
(function () {
  'use strict';

  const GRID_STEP = 10; // degrees — matches the 10° fetch grid

  function ensureData() {
    window.__weatherDataPromise = window.__weatherDataPromise
      || fetch('./data/weather.json').then(r => r.json());
    return window.__weatherDataPromise;
  }

  // Scientific colormap for surface air temperature (Celsius).
  // Spans -70°C (Antarctic plateau) → +50°C (hot desert surface).
  // Follows the conventional meteorological blue-cyan-green-yellow-red scale.
  // Precomputed once per datum; never called again during rendering.
  function tempColor(t) {
    const stops = [
      [-70, [ 20,   0,  80]],  // deep indigo  (Antarctic extremes)
      [-50, [  0,  30, 180]],  // dark blue
      [-30, [  0, 100, 255]],  // blue
      [-10, [  0, 210, 240]],  // cyan
      [  0, [ 80, 220, 180]],  // cyan-green   (freezing point)
      [ 10, [ 60, 200,  60]],  // green
      [ 20, [220, 220,   0]],  // yellow
      [ 30, [255, 130,   0]],  // orange
      [ 40, [220,  30,   0]],  // red
      [ 50, [120,   0,  20]],  // deep red     (desert extremes)
    ];
    const alpha = 0.50;

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
    active:  false,
    _globe:  null,
    _loaded: false,

    init(globe) {
      this._globe = globe;
    },

    _load() {
      if (this._loaded) return;
      this._loaded = true;

      ensureData().then(data => {
        const HALF = GRID_STEP / 2;
        const cells = data.map(d => ({
          color:   tempColor(d.t),   // precomputed — zero cost at render time
          polygon: [[
            [d.lon - HALF, d.lat - HALF],
            [d.lon + HALF, d.lat - HALF],
            [d.lon + HALF, d.lat + HALF],
            [d.lon - HALF, d.lat + HALF],
            [d.lon - HALF, d.lat - HALF],
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
        .polygonCapColor(d => d.color)   // property lookup only — no computation
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
