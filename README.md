# sawyersuzuki.github.io

Personal portfolio — single-page HTML/CSS/JS, no build step, deployable to GitHub Pages.

## File structure

```
/
├── index.html          # Home page: nav + Globe.gl globe + intro
├── projects.html       # Projects listing
├── css/
│   └── style.css       # All styles (CSS variables for theming)
└── js/
    ├── globe.js        # Globe initialisation, rotation, resize
    └── layers/         # ERA5 / atmospheric data overlays (see below)
        └── .gitkeep
```

## Deploying to GitHub Pages

1. Create a repo named `<your-username>.github.io` (or any repo with Pages enabled).
2. Push this folder's contents to the `main` branch.
3. In repo Settings → Pages, set source to `main` / `/ (root)`.
4. The site will be live at `https://<your-username>.github.io`.

No build step. No dependencies to install. The only external resources are:
- Google Fonts (Inter) — loaded via `<link>` in both HTML files.
- Globe.gl — loaded via `<script src="https://unpkg.com/globe.gl@2/...">` in `index.html`.

## Adding a data layer to the globe

All globe overlay work goes in `js/layers/`. The pattern is intentionally
simple so each layer is self-contained and can be added or removed without
touching `globe.js`.

### Steps

1. **Create** `js/layers/<name>.js` with this shape:

   ```js
   // js/layers/wind.js  — ERA5 wind vector overlay example
   export function applyLayer(globe) {
     // `globe` is the Globe.gl instance.
     // Use any Globe.gl API here, e.g.:
     //   globe.customLayerData([...]).customThreeObject(...)
     //   globe.htmlElementsData([...]).htmlElement(...)
   }
   ```

2. **Load your data** inside that function. For ERA5 you'll typically fetch a
   pre-processed JSON file (wind vectors sampled to a regular grid) from the
   same repo or a CDN, then map it onto Globe.gl's `customLayerData` API.

3. **Register the layer** in `index.html` by adding a module script after
   `globe.js` is loaded:

   ```html
   <script type="module">
     import { applyLayer as applyWind } from './js/layers/wind.js';
     // Globe.gl attaches itself to window.Globe; wait for globe.js to run first.
     document.addEventListener('DOMContentLoaded', () => {
       // globe.js exposes the instance via window.__globe
       applyWind(window.__globe);
     });
   </script>
   ```

   You'll also need to expose the globe instance in `globe.js`:
   ```js
   window.__globe = globe;
   ```

### ERA5 data tips

- Download via the [CDS API](https://cds.climate.copernicus.eu/) or use
  pre-processed NetCDF → GeoJSON conversion scripts.
- For wind vectors, sample u/v components onto a ~2° lat/lon grid and export
  as a flat JSON array: `[{ lat, lng, u, v }, ...]`.
- For SST, a texture-mapped image (e.g. `globe.customGlobeImageUrl(...)` swapped
  at runtime) is simpler than per-point rendering.
