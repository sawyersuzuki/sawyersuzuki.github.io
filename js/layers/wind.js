/**
 * Wind layer — animated 10m wind vectors on the globe.
 *
 * Uses Globe.gl's arcsData API with animated dash patterns.
 * 20° sparse grid (~153 arcs), precomputed colours, fixed animation time.
 *
 * Note on units: weather.json stores windspeed (spd/u/v) in km/h because
 * Open-Meteo's current_weather object returns km/h by default. SCALE and
 * the colour normalization are adjusted accordingly:
 *   SCALE        0.18 deg/(km/h)  ≡ the original 0.65 deg/(m/s)
 *   colour norm  speed/50 km/h    ≡ the original speed/14 m/s
 */
(function () {
  'use strict';

  const GRID_STEP = 20;   // degrees — subsample from 10° weather.json grid
  const SCALE     = 0.18; // visual degrees per km/h  (≈ 0.65 deg per m/s)

  function ensureData() {
    window.__weatherDataPromise = window.__weatherDataPromise
      || fetch('./data/weather.json').then(r => r.json());
    return window.__weatherDataPromise;
  }

  // Precomputed once per arc; never called again during rendering.
  function windColor(speedKmh, alpha) {
    const norm = Math.min(1, speedKmh / 50);  // 50 km/h ≈ 14 m/s → full brightness
    const r = Math.round(norm * 80);
    const g = Math.round(160 + norm * 95);
    return `rgba(${r},${g},255,${alpha !== undefined ? alpha : 0.35 + norm * 0.55})`;
  }

  window.windLayer = {
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
        const arcs = data
          .filter(d => d.lat % GRID_STEP === 0 && d.lon % GRID_STEP === 0)
          .map(d => {
            const speed  = d.spd || Math.sqrt(d.u ** 2 + d.v ** 2);
            const coslat = Math.max(0.05, Math.cos(d.lat * Math.PI / 180));
            return {
              startLat:  d.lat,
              startLng:  d.lon,
              endLat:    Math.max(-88, Math.min(88, d.lat + d.v * SCALE)),
              endLng:    d.lon + (d.u * SCALE) / coslat,
              colorTail: windColor(speed, 0.04),   // precomputed
              colorHead: windColor(speed),           // precomputed
              stroke:    0.3 + Math.min(0.4, speed / 80),  // precomputed
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
        .arcColor(d => [d.colorTail, d.colorHead])  // property lookup only
        .arcStroke(d => d.stroke)                    // property lookup only
        .arcAltitude(0.004)
        .arcDashLength(0.55)
        .arcDashGap(0.45)
        .arcDashAnimateTime(2200);  // single constant — no per-arc tracking
    },

    show() {
      this.active = true;
      this._load();
      if (this._globe.__windArcs) this._apply();
    },

    hide() {
      this.active = false;
      this._globe.arcsData([]);
    },

    toggle() {
      this.active ? this.hide() : this.show();
    },
  };
})();
