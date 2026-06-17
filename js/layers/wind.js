(function () {
  'use strict';

  const TARGET_STEP = 3;   // interpolated grid step in degrees (~10x denser than raw 10° data)
  const SOURCE_STEP = 10;  // weather.json grid step
  const SCALE = 0.18;      // visual degrees per km/h

  function ensureData() {
    window.__weatherDataPromise = window.__weatherDataPromise
      || fetch('./data/weather.json').then(r => r.json());
    return window.__weatherDataPromise;
  }

  // Bilinearly interpolate the 10° wind field onto a denser grid.
  // Returns {u, v} at any (lat, lon) by weighting the four surrounding data points.
  function interpolateGrid(data, step) {
    const lookup = {};
    data.forEach(d => {
      if (!lookup[d.lat]) lookup[d.lat] = {};
      lookup[d.lat][d.lon] = { u: d.u, v: d.v };
    });

    function getUV(lat, lon) {
      const lat0 = Math.floor(lat / SOURCE_STEP) * SOURCE_STEP;
      const lat1 = lat0 + SOURCE_STEP;
      const lon0 = Math.floor(lon / SOURCE_STEP) * SOURCE_STEP;
      const lon1 = lon0 + SOURCE_STEP;
      const tLat = (lat - lat0) / SOURCE_STEP;
      const tLon = (lon - lon0) / SOURCE_STEP;

      const get = (la, lo) => lookup[la] && lookup[la][lo];
      const p00 = get(lat0, lon0), p10 = get(lat1, lon0);
      const p01 = get(lat0, lon1), p11 = get(lat1, lon1);

      let u = 0, v = 0, w = 0;
      const add = (p, weight) => { if (p) { u += p.u * weight; v += p.v * weight; w += weight; } };
      add(p00, (1 - tLat) * (1 - tLon));
      add(p10,       tLat  * (1 - tLon));
      add(p01, (1 - tLat) *       tLon);
      add(p11,       tLat  *       tLon);

      return w > 0 ? { u: u / w, v: v / w } : null;
    }

    const result = [];
    for (let lat = -80; lat <= 80; lat += step) {
      for (let lon = -180; lon <= 177; lon += step) {
        const uv = getUV(lat, lon);
        if (uv) result.push({ lat, lon, u: uv.u, v: uv.v, spd: Math.sqrt(uv.u ** 2 + uv.v ** 2) });
      }
    }
    return result;
  }

  function windColor(speedKmh, alpha) {
    const norm = Math.min(1, speedKmh / 50);
    const r = Math.round(norm * 80);
    const g = Math.round(160 + norm * 95);
    return `rgba(${r},${g},255,${alpha !== undefined ? alpha : 0.35 + norm * 0.55})`;
  }

  window.windLayer = {
    active:  false,
    _globe:  null,
    _loaded: false,

    init(globe) { this._globe = globe; },

    _load() {
      if (this._loaded) return;
      this._loaded = true;

      ensureData().then(data => {
        const grid = interpolateGrid(data, TARGET_STEP);
        const arcs = grid.filter((_, i) => i % 4 !== 0).map(d => {
          const coslat = Math.max(0.05, Math.cos(d.lat * Math.PI / 180));
          return {
            startLat:  d.lat,
            startLng:  d.lon,
            endLat:    Math.max(-88, Math.min(88, d.lat + d.v * SCALE)),
            endLng:    d.lon + (d.u * SCALE) / coslat,
            colorTail: windColor(d.spd, 0.04),
            colorHead: windColor(d.spd),
            stroke:    0.3 + Math.min(0.4, d.spd / 80),
          };
        });

        this._globe.__windArcs = arcs;
        if (this.active) this._apply();
      });
    },

    _apply() {
      this._globe
        .arcsData(this._globe.__windArcs)
        .arcStartLat(d => d.startLat)
        .arcStartLng(d => d.startLng)
        .arcEndLat(d => d.endLat)
        .arcEndLng(d => d.endLng)
        .arcColor(d => [d.colorTail, d.colorHead])
        .arcStroke(d => d.stroke)
        .arcAltitude(0.004)
        .arcDashLength(0.55)
        .arcDashGap(0.45)
        .arcDashAnimateTime(2200);
    },

    show()   { this.active = true;  this._load(); if (this._globe.__windArcs) this._apply(); },
    hide()   { this.active = false; this._globe.arcsData([]); },
    toggle() { this.active ? this.hide() : this.show(); },
  };
})();
