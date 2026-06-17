(function () {
  'use strict';

  const GRID_STEP = 10; // use full 10° resolution — baked into texture, zero render cost

  function ensureData() {
    window.__weatherDataPromise = window.__weatherDataPromise
      || fetch('./data/weather.json').then(r => r.json());
    return window.__weatherDataPromise;
  }

  function tempColor(t) {
    const stops = [
      [-70, [ 20,   0,  80]],
      [-50, [  0,  30, 180]],
      [-30, [  0, 100, 255]],
      [-10, [  0, 210, 240]],
      [  0, [ 80, 220, 180]],
      [ 10, [ 60, 200,  60]],
      [ 20, [220, 220,   0]],
      [ 30, [255, 130,   0]],
      [ 40, [220,  30,   0]],
      [ 50, [120,   0,  20]],
    ];
    if (t <= stops[0][0]) return stops[0][1];
    if (t >= stops[stops.length - 1][0]) return stops[stops.length - 1][1];
    for (let i = 0; i < stops.length - 1; i++) {
      const [t0, c0] = stops[i];
      const [t1, c1] = stops[i + 1];
      if (t >= t0 && t <= t1) {
        const f = (t - t0) / (t1 - t0);
        return [
          Math.round(c0[0] + f * (c1[0] - c0[0])),
          Math.round(c0[1] + f * (c1[1] - c0[1])),
          Math.round(c0[2] + f * (c1[2] - c0[2])),
        ];
      }
    }
    return [128, 128, 128];
  }

  // Build a complete grid, filling missing cells via nearest-neighbor so no black holes appear.
  function fillGrid(data) {
    const lats = [], lons = [];
    for (let lat = -80; lat <= 80; lat += GRID_STEP) lats.push(lat);
    for (let lon = -170; lon <= 170; lon += GRID_STEP) lons.push(lon);

    // Index known values
    const known = {};
    data.forEach(d => { known[`${d.lat},${d.lon}`] = d.t; });

    // Global mean as ultimate fallback
    const vals = data.map(d => d.t);
    const mean = vals.reduce((a, b) => a + b, 0) / vals.length;

    const filled = [];
    lats.forEach(lat => {
      lons.forEach(lon => {
        const key = `${lat},${lon}`;
        if (known[key] !== undefined) {
          filled.push({ lat, lon, t: known[key] });
          return;
        }
        // Nearest-neighbor: expand search radius until a known cell is found
        let t = null;
        for (let r = 1; r <= 5 && t === null; r++) {
          for (let dl = -r; dl <= r && t === null; dl++) {
            for (let dk = -r; dk <= r && t === null; dk++) {
              if (Math.abs(dl) !== r && Math.abs(dk) !== r) continue;
              const nlat = lat + dl * GRID_STEP;
              const nlon = lon + dk * GRID_STEP;
              const v = known[`${nlat},${nlon}`];
              if (v !== undefined) t = v;
            }
          }
        }
        filled.push({ lat, lon, t: t !== null ? t : mean });
      });
    });
    return filled;
  }

  // Load the base earth texture, composite temperature cells on top, return data URL.
  // Uses globeImageUrl (equirectangular) so it auto-rotates with the globe.
  function buildCompositeTexture(baseUrl, data) {
    const grid = fillGrid(data);
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => {
        const W = img.naturalWidth  || 1024;
        const H = img.naturalHeight || 512;
        const canvas = document.createElement('canvas');
        canvas.width = W; canvas.height = H;
        const ctx = canvas.getContext('2d');

        ctx.drawImage(img, 0, 0, W, H);

        const cellW = Math.ceil(GRID_STEP / 360 * W) + 1; // +1 closes sub-pixel gaps
        const cellH = Math.ceil(GRID_STEP / 180 * H) + 1;

        grid.forEach(d => {
          const [r, g, b] = tempColor(d.t);
          ctx.fillStyle = `rgba(${r},${g},${b},0.52)`;
          const x = (d.lon + 180) / 360 * W;
          const y = (90 - d.lat) / 180 * H;
          ctx.fillRect(x - cellW / 2, y - cellH / 2, cellW, cellH);
        });

        try {
          resolve(canvas.toDataURL('image/jpeg', 0.88));
        } catch (e) {
          reject(e); // CORS taint
        }
      };
      img.onerror = reject;
      img.src = baseUrl;
    });
  }

  window.temperatureLayer = {
    active:       false,
    _globe:       null,
    _loaded:      false,
    _originalUrl: null,
    _compositeUrl: null,

    init(globe) {
      this._globe = globe;
      // Capture current URL before any modification
      this._originalUrl = globe.globeImageUrl();
    },

    _load() {
      if (this._loaded) return;
      this._loaded = true;

      const baseUrl = this._originalUrl
        || '//unpkg.com/three-globe/example/img/earth-dark.jpg';

      Promise.all([ensureData(), Promise.resolve()])
        .then(([data]) => buildCompositeTexture(baseUrl, data))
        .then(url => {
          this._compositeUrl = url;
          if (this.active) this._apply();
        })
        .catch(err => {
          console.warn('Temperature layer: could not composite texture (CORS?)', err);
          this._loaded = false; // allow retry
        });
    },

    _apply() {
      if (this._compositeUrl) this._globe.globeImageUrl(this._compositeUrl);
    },

    show() {
      this.active = true;
      this._load();
      if (this._compositeUrl) this._apply();
    },

    hide() {
      this.active = false;
      if (this._originalUrl !== null) this._globe.globeImageUrl(this._originalUrl);
    },

    toggle() { this.active ? this.hide() : this.show(); },
  };
})();
