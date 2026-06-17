/**
 * Temperature layer — 2m temperature heatmap draped on the globe.
 *
 * Uses Globe.gl's polygonsData API with 5° lat/lon cells coloured by
 * temperature. Toggle via window.temperatureLayer.toggle(globe).
 */
(function () {
  'use strict';

  const STEP = 5; // degrees — matches weather.json grid resolution

  // Shared data promise so both layers only fetch once
  window.__weatherDataPromise = window.__weatherDataPromise
    || fetch('./data/weather.json').then(r => r.json());

  // Interpolated colormap: cold blue → cyan → green → yellow → hot red
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
    const alpha = 0.48;
    if (t <= stops[0][0])   return `rgba(${stops[0][1].join(',')},${alpha})`;
    if (t >= stops[stops.length-1][0]) return `rgba(${stops[stops.length-1][1].join(',')},${alpha})`;
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
    active: false,

    init(globe) {
      window.__weatherDataPromise.then(data => {
        // Build one GeoJSON-ish cell polygon per grid point
        const cells = data.map(d => ({
          t: d.t,
          polygon: [[
            [d.lon - STEP / 2, d.lat - STEP / 2],
            [d.lon + STEP / 2, d.lat - STEP / 2],
            [d.lon + STEP / 2, d.lat + STEP / 2],
            [d.lon - STEP / 2, d.lat + STEP / 2],
            [d.lon - STEP / 2, d.lat - STEP / 2],
          ]],
        }));
        globe.__tempCells = cells;
        if (this.active) this._apply(globe);
      });
    },

    _apply(globe) {
      globe
        .polygonsData(globe.__tempCells)
        .polygonGeoJsonGeometry(d => ({ type: 'Polygon', coordinates: d.polygon }))
        .polygonCapColor(d => tempColor(d.t))
        .polygonSideColor(() => 'transparent')
        .polygonStrokeColor(() => false)
        .polygonAltitude(0.001);
    },

    show(globe) {
      this.active = true;
      if (globe.__tempCells) this._apply(globe);
    },

    hide(globe) {
      this.active = false;
      globe.polygonsData([]);
    },

    toggle(globe) {
      this.active ? this.hide(globe) : this.show(globe);
    },
  };
})();
