# Weather Model Comparison

Live at [sawyersuzuki.com/projects/weather-model-comparison](https://sawyersuzuki.com/projects/weather-model-comparison/).

A personal dashboard for comparing weather models over the contiguous US, built around extreme cold and heat: where the models disagree, how their forecasts verified, how they handled past events, and how all of that lines up with gas and power prices.

Everything runs on free public data with no API keys. [DECISIONS.md](DECISIONS.md) records the assumptions, the changes made to the original brief, and what has and has not been verified.

## Quick start

This pipeline lives in the `projects/weather-model-comparison/` folder of the website repository; run every command from that folder.

```bash
cd projects/weather-model-comparison
```

```bash
uv venv && uv pip install -e ".[dev]"
```

```bash
.venv/bin/wxcc update
```

```bash
.venv/bin/wxcc serve
```

`update` fetches the newest runs of every model, refreshes the truth series and market data, and takes under a minute. `serve` rebuilds the dashboard and opens it at http://localhost:8765. The dashboard is a single file, `site/index.html`, which also opens directly in a browser with no server.

The website's scheduled workflow runs `update` twice a day, commits the result and republishes the site, so the live page is always current. Locally, `git pull` followed by `wxcc serve` is all you need.

Maps are kept out of git. On a fresh clone the Maps tab is empty until you run `wxcc fields pull` (needs the GitHub CLI, signed in) or `wxcc update` picks up the next 00Z runs.

## Commands

| Command | What it does |
|---|---|
| `wxcc update` | The daily job: latest runs of all models, truth, market data. Safe to run any number of times. |
| `wxcc backfill --model aifs --start 2025-01-01 --end 2025-03-31` | Extend history. Prints download size, disk use and runtime, then asks. Skips what is stored; safe to interrupt and re-run. `--model all` covers every forecast model; `--cycles 0` limits to 00Z runs. |
| `wxcc query --model gfs --region TX --init 2026-11-15T00` | Ask what is stored. Filters: `--model --region --start --end --init --method`; `--csv` for export. |
| `wxcc inventory` | Date ranges and run counts per model. |
| `wxcc models` | Every model: source, licence, how far back its free archive goes. |
| `wxcc build` / `wxcc serve` | Rebuild the dashboard / rebuild and serve it locally. |
| `wxcc market` | Refresh Henry Hub, EIA storage and power prices only. |
| `wxcc fields status` / `publish` / `pull` | Daily temperature maps: local cache, and long-term copies on GitHub Releases. |
| `wxcc validate --start ... --end ...` | Compare ERA5 degree days with NOAA CPC. |
| `wxcc validate-stations --month 2026-01` | Compare ERA5 with 31 big-city airport stations. |

In a notebook, the same query layer is `from wxcc import store; store.query(model="gfs", region="TX")`, which returns a pandas DataFrame.

## Models and how far back each goes

| Model | Type | Free archive starts | Lead |
|---|---|---|---|
| GFS | physics, NOAA | Jan 2021 | 16 days |
| IFS HRES | physics, ECMWF | Jan 2023 | 10 days |
| AIFS | AI, ECMWF | Mar 2024 | 15 days |
| AIGFS | AI, NOAA (GraphCastGFS before Apr 2026) | Feb 2024 | 16 days |
| GraphCast | AI, run by NOAA/CIRA from GFS analysis | Jan 2022 | 10 days |
| Pangu-Weather | AI, run by NOAA/CIRA | Oct 2020 | 10 days |
| FourCastNet v2 | AI, run by NOAA/CIRA | Oct 2020 | 10 days |
| Aurora | AI, run by NOAA/CIRA | Jan 2025 | 10 days |
| ERA5 | reanalysis (truth) | 1940; about a week behind | |
| GFS analysis | provisional truth for the latest week | Jan 2021 | |

Anything in those ranges can be backfilled on demand. Already stored: see `wxcc inventory` or the dashboard's Data tab.

## The dashboard

- **Model vs model:** daily degree days by model for one run; totals for days 1-5, 6-10 and 11-15 against normal and against the previous run; how a fixed window's forecast has changed run to run.
- **Forecast vs reality:** error and bias by lead time against ERA5, with the caveat that most AI models were trained on ERA5.
- **Extreme events:** a dropdown of seven events from Uri (Feb 2021) to Fern (Jan 2026), plus any custom dates, showing how each model's forecast for the event evolved as it approached.
- **Maps:** daily-mean temperature from the latest 00Z run of each model, as differences from the model mean or as temperature.
- **Market link:** weekly storage change against weekly HDD, Henry Hub against forecast revisions, and day-ahead power prices against regional degree days.
- **Data:** what is stored, sources, licences, and Colab lab runs.

Each view opens with a short "What am I looking at?" note.

## Reading the numbers

- **HDD / CDD:** heating and cooling degree days against a 65 F base. A day averaging 45 F is 20 HDD.
- **Population-weighted:** each 25 km grid cell counts in proportion to the people living there (2020 Census).
- **Regions:** `NE MA ENC WNC SA ESC WSC MTN PAC` are the nine census divisions; `TX CA PNW NY` are states or state groups that match power markets; `CONUS` is everything.
- **Day:** 06 UTC to 06 UTC, about midnight to midnight Central.
- **Lead day:** valid date minus run date. A 12Z run's first complete day is lead day 1.
- **Level vs other sources:** these degree days run about 5-10% below NOAA CPC's in winter because of how each averages over space. They are consistent with themselves; do not mix them with CPC or EIA figures without re-basing. Details in DECISIONS.md.

## Colab lab (Earth2Studio)

Two notebooks in `notebooks/` run models on a Colab GPU and write results into the same store, so the dashboard shows them as "Lab: model" after the next build:

- `lab_forecast.ipynb`: FourCastNet 3, Atlas, AIFS, GraphCast, Pangu or SFNO for a chosen start time and lead, from GFS, IFS or ERA5 initial conditions.
- `lab_corrdiff.ipynb`: CorrDiff downscaling of ERA5 to 3 km over CONUS, with degree days computed on the 3 km grid.

Each needs a GitHub token saved as the Colab secret `GITHUB_TOKEN` (fine-grained, Contents read and write on this repo only). Estimated cost is about 1-1.5 compute units for the first forecast of a session and 0.1-0.3 for each one after; every run records its measured time and estimated units in its manifest. These notebooks have been tested on CPU with a test model only; no GPU model has been run from them yet.

## Storage

| Where | What | Size now |
|---|---|---|
| `data/regional/` | Regional series: one Parquet file per init day, monthly truth files | 8 MB (3,255 runs, 3,962 truth days) |
| `data/manifests/` | One JSON line per run: source, steps, settings | 1.5 MB |
| `data/market/` | Henry Hub, storage, power prices (CSV) | 0.1 MB |
| `data/static/` | Population weights, state outlines | 0.1 MB |
| `.cache/` (not in git) | Daily temperature maps; capped at 3 GB and pruned automatically | 0.65 GB after the full backfill |
| GitHub Releases `fields-<year>` | Long-term copies of the maps, one zip per model and month | written by the scheduled job |

A year of twice-daily runs of all eight models adds about 15 MB to the repository.

Downloads are streamed and cropped to CONUS in memory; no global file is ever written to disk.

## Automation

`.github/workflows/weather-model-comparison.yml` (at the root of the website repository) runs at 10:17 and 22:17 UTC: update, publish maps, commit data, build the dashboard with a link back to the Projects page, and deploy the whole website to GitHub Pages. A push to `main` (for example an edit to `projects.html`) rebuilds and redeploys without fetching data. Actions minutes are free because the repository is public. A manual run also accepts a date range to backfill 00Z runs and regenerate their maps.

The site is deployed by this workflow rather than straight from the branch, so the 7 MB dashboard is never committed: only the small data files are. That needs Settings > Pages > Source set to **GitHub Actions** (one-time).

`wxcc build --out <folder> --home-link <url>` writes the page anywhere and adds the link back to the website.

## Data sources and attribution

- **ERA5:** contains modified Copernicus Climate Change Service information; accessed through Google's ARCO-ERA5.
- **GFS, AIGFS:** NOAA, via NOAA Open Data Dissemination on AWS.
- **IFS, AIFS:** © ECMWF, open data under CC BY 4.0.
- **GraphCast, Pangu-Weather, FourCastNet v2, Aurora:** forecasts produced and published by NOAA/CIRA (Radford et al. 2025, BAMS, doi:10.1175/BAMS-D-24-0057.1).
- **Population:** US Census Bureau, 2020 Centers of Population. **State outlines:** us-atlas (ISC), from Census boundary files.
- **Validation:** NOAA Climate Prediction Center degree days; Iowa Environmental Mesonet station summaries (fetched on demand, not stored).
- **Market:** EIA (Henry Hub via FRED, weekly storage); NYISO, MISO and CAISO public market data.

This is a personal research tool, not a forecast service.
