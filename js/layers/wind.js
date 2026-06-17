/**
 * Wind layer — animated 10m wind vectors on the globe.
 *
 * Lazy-loaded: data/weather.json is only fetched the first time this layer
 * is shown. Arc colors are precomputed once so Globe.gl does zero color
 * computation during rendering.
 *
 * Resolution: 20° grid (≈ 162 arcs) — readable density, smooth frame rate.
 */
(function () {
  'use strict';

  const GRID_STEP = 20; // degrees — sparse enough for smooth animation

  function ensureData() {
    window.__weatherDataPromise = window.__weatherDataPromise
      || fetch('./data/weather.json').then(r => r.json());
    return window.__weatherDataPromise;
  }

  // Precomputed once per arc; never called again during rendering.
  function windColor(speed, alpha) {
    const norm = Math.min(1, speed / 14);
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
      // No fetch here — wait until the user actually toggles the layer.
    },

    _load() {
      if (this._loaded) return;
      this._loaded = true;

      ensureData().then(data => {
        const SCALE = 0.65; // visual degrees per m/s

        const arcs = data
          .filter(d => d.lat % GRID_STEP === 0 && d.lon % GRID_STEP === 0)
          .map(d => {
            const speed  = d.spd || Math.sqrt(d.u ** 2 + d.v ** 2);
            const coslat = Math.max(0.05, Math.cos(d.lat * Math.PI / 180));
            return {
              startLat:   d.lat,
              startLng:   d.lon,
              endLat:     Math.max(-88, Math.min(88, d.lat + d.v * SCALE)),
              endLng:     d.lon + (d.u * SCALE) / coslat,
              colorTail:  windColor(speed, 0.04),  // precomputed
              colorHead:  windColor(speed),          // precomputed
              stroke:     0.3 + Math.min(0.4, speed / 25),  // precomputed
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
