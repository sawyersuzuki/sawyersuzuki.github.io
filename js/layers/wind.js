/**
 * Wind layer — animated 10m wind vectors on the globe.
 *
 * Uses Globe.gl's arcsData API with animated dash patterns to show wind
 * direction and speed at a 10° sparse grid. Toggle via window.windLayer.toggle(globe).
 */
(function () {
  'use strict';

  window.__weatherDataPromise = window.__weatherDataPromise
    || fetch('./data/weather.json').then(r => r.json());

  function windColor(speed, alpha) {
    // Slow: dim blue → fast: bright cyan-white
    const norm = Math.min(1, speed / 14);
    const r = Math.round(norm * 80);
    const g = Math.round(160 + norm * 95);
    const b = 255;
    return `rgba(${r},${g},${b},${alpha !== undefined ? alpha : (0.35 + norm * 0.55)})`;
  }

  window.windLayer = {
    active: false,

    init(globe) {
      window.__weatherDataPromise.then(data => {
        // Subsample to 10° grid for arc density that reads well visually
        const sparse = data.filter(d => d.lat % 10 === 0 && d.lon % 10 === 0);
        const SCALE = 0.65; // visual degrees per m/s

        const arcs = sparse.map(d => {
          const speed = d.spd || Math.sqrt(d.u ** 2 + d.v ** 2);
          const latRad = d.lat * Math.PI / 180;
          const coslat = Math.max(0.05, Math.cos(latRad));
          return {
            startLat: d.lat,
            startLng: d.lon,
            endLat: Math.max(-88, Math.min(88, d.lat + d.v * SCALE)),
            endLng: d.lon + (d.u * SCALE) / coslat,
            speed,
          };
        });

        globe.__windArcs = arcs;
        if (this.active) this._apply(globe);
      });
    },

    _apply(globe) {
      globe
        .arcsData(globe.__windArcs)
        .arcStartLat(d => d.startLat)
        .arcStartLng(d => d.startLng)
        .arcEndLat(d => d.endLat)
        .arcEndLng(d => d.endLng)
        .arcColor(d => [windColor(d.speed, 0.04), windColor(d.speed)])
        .arcStroke(d => 0.25 + Math.min(0.5, d.speed / 20))
        .arcAltitude(0.004)
        .arcDashLength(0.55)
        .arcDashGap(0.45)
        .arcDashAnimateTime(d => 1800 + (14 - Math.min(14, d.speed)) * 160);
    },

    show(globe) {
      this.active = true;
      if (globe.__windArcs) this._apply(globe);
    },

    hide(globe) {
      this.active = false;
      globe.arcsData([]);
    },

    toggle(globe) {
      this.active ? this.hide(globe) : this.show(globe);
    },
  };
})();
