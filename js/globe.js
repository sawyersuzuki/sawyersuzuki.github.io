/**
 * Globe initialisation + auto-rotation.
 *
 * DATA LAYER EXTENSION POINT
 * --------------------------
 * To add an ERA5 / atmospheric overlay, create a file in js/layers/ (e.g.
 * layers/wind.js) that exports a single function:
 *
 *   export function applyLayer(globe) { ... }
 *
 * That function receives the Globe.gl instance and can call any Globe.gl API
 * (customLayerData, imageUrl, htmlElementsData, etc.) to attach the overlay.
 * Then import and call it here after the globe is initialised:
 *
 *   import { applyLayer as applyWind } from './layers/wind.js';
 *   applyWind(globe);
 *
 * No other files need to change.
 */

(function () {
  'use strict';

  const container = document.getElementById('globe-container');
  if (!container) return;

  const size = container.clientWidth;

  const globe = Globe({ animateIn: false })(container)
    .width(size)
    .height(size)
    .backgroundColor('rgba(0,0,0,0)')
    // globe surface
    .globeImageUrl(
      'https://unpkg.com/three-globe/example/img/earth-dark.jpg'
    )
    // atmosphere glow
    .atmosphereColor('#38bdf8')
    .atmosphereAltitude(0.12)
    // graticule (lat/lon grid)
    .showGraticules(true)
    // land polygons
    .showAtmosphere(true);

  // Style the graticule lines via the underlying Three.js object
  globe.onGlobeReady(() => {
    // Give Three.js a tick to populate internal objects
    requestAnimationFrame(() => {
      const scene = globe.scene();
      scene.traverse((obj) => {
        if (obj.isMesh && obj.material) {
          const name = obj.name || '';
          if (name.includes('graticule') || name.includes('Graticule')) {
            obj.material.color.set(0x1e3a5f);
            obj.material.opacity = 0.6;
            obj.material.transparent = true;
          }
        }
      });
    });
  });

  // Auto-rotation
  let animFrameId;
  let isDragging = false;

  function rotate() {
    if (!isDragging) {
      const controls = globe.controls();
      controls.autoRotate = true;
      controls.autoRotateSpeed = 0.6;
    }
    animFrameId = requestAnimationFrame(rotate);
  }

  container.addEventListener('mousedown', () => { isDragging = true; });
  container.addEventListener('touchstart', () => { isDragging = true; }, { passive: true });
  window.addEventListener('mouseup', () => { isDragging = false; });
  window.addEventListener('touchend', () => { isDragging = false; });

  globe.controls().enableZoom = false;
  globe.controls().autoRotate = true;
  globe.controls().autoRotateSpeed = 0.6;

  rotate();

  // Expose globe instance for data layers (see js/layers/)
  window.__globe = globe;

  // Resize handling
  let resizeTimer;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      const w = container.clientWidth;
      globe.width(w).height(w);
    }, 150);
  });
})();
