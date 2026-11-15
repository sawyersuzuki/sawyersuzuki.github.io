# Decisions

Assumptions, changes to the original brief, and trade-offs. Facts marked "checked" were verified against the source on 2026-11-15.

## Changes to the brief

| # | Brief said | What we do instead | Why |
|---|---|---|---|
| 1 | Open archives roll off in days, so every unarchived day is lost | The update job is for freshness; backfill covers gaps | Checked: ECMWF's AWS mirror (`s3://ecmwf-forecasts`) holds every run since 2023-01-18 and NOAA's GFS bucket since 2021-01-01. Only ECMWF's own portal is short-lived. AWS retention is not guaranteed, so we still archive twice a day. |
| 2 | "dynamical.org forecasts" as a model | Not used as a source at all | It re-hosts GFS, IFS ENS and AIFS (no IFS HRES). Reading the original GRIB by byte range turned out simpler and needs fewer dependencies than Zarr/Icechunk. It remains the obvious source for ensembles later. |
| 3 | AI models come from Earth2Studio on Colab | GraphCast, Pangu, FourCastNet v2, Aurora and NOAA's AIGFS come from public NOAA archives with no GPU; Colab is for models nobody publishes and for custom hindcasts | NOAA/CIRA re-runs these daily and keeps history to Oct 2020 (GraphCast from 2022). That gives eight forecast models in V1 instead of the proposed six. |
| 4 | Regions: census divisions or gas-demand regions | Nine census divisions plus Texas, California, Pacific Northwest, New York and CONUS | Uri and the 2021 heat dome are state-scale events that a census division dilutes (Pacific is 77% California by population). The four extra regions also match ERCOT, CAISO and NYISO for the market link. |
| 5 | HDD only | HDD, CDD, their sum, and population-weighted temperature | Extreme heat is a stated focus. HDD + CDD also makes verification meaningful in shoulder seasons, when HDD alone is near zero. |
| 6 | ERA5 as truth | ERA5, with GFS analysis as flagged provisional truth where ERA5 is missing | ERA5 lags about a week, and its near-real-time files have occasional missing hours. |
| 7 | Dashboard on GitHub Pages | One self-contained HTML file, opened locally; a Pages job is ready for when the repo is public | Checked: Pages needs a public repo on GitHub Free. The file needs no server at all. |
| 8 | Large data on a free tier (Hugging Face was the agreed default) | GitHub Release assets on this repo | No extra account or token; private while the repo is private; the scheduled job can write to it with its built-in token. Changed after you asked me to finish without further input. Easy to revisit. |
| 9 | CorrDiff for CONUS | Notebook provided, gated on GPU memory | Earth2Studio rates `CorrDiffEra5Hrrr` for 80 GB; Colab Pro does not guarantee that. The notebook stops before inference if the GPU is too small. |
| 10 | ISO LMPs | NYISO, MISO and CAISO only | Those publish keyless files. ERCOT and PJM are free but need registered API keys, which I cannot create for you. |

## Definitions

- **Base temperature:** 65 F.
- **Day:** label D covers D 06:00 UTC to D+1 06:00 UTC (about midnight to midnight Central). The 9am Central gas day was considered and deferred; it would need hourly data that several AI models do not provide.
- **Daily temperature (`mean6h`, the default):** mean of the 06, 12, 18 and 00 UTC values, the one definition every model supports. `minmax1h` ((Tmax+Tmin)/2 from hourly data, the NOAA convention) and `mean1h` exist for ERA5; the difference at CONUS level in January 2026 was under 1%.
- **Order of operations:** degree days are computed per grid cell, then population-weighted. HDD of an averaged temperature is not the average HDD.
- **Incomplete days are dropped**, never estimated. A 12Z run therefore starts at lead day 1.
- **Lead day:** valid date minus run date. Windows "days 1-5, 6-10, 11-15" use lead days.
- **Population weights:** 2020 Census tract centres of population, each snapped to the nearest 0.25 degree grid point (8,279 state-cell pairs, 329.3 million people).
- **Grid:** 0.25 degree, 24N-50N, 125W-66.5W (105 x 235). Models on other grids are interpolated bilinearly (IFS before February 2024 at 0.4 degrees; AIFS in early 2024 on a reduced Gaussian grid).
- **Normals:** 2016-2025 ERA5, mean of a centred 15-day window per calendar day. Ten years is the gas-market convention and keeps the ERA5 backfill small; a 30-year normal is one backfill command away.
- **Events:** windows are day labels around the peak of the population-weighted signal, listed in `src/wxcc/events.py`.

## Models and history

| Model | Source read | Earliest run | Lead | Licence |
|---|---|---|---|---|
| GFS | NOAA S3, GRIB byte ranges | 2021-01-01 | 16 d | Public domain |
| IFS HRES | ECMWF open data on AWS | 2023-01-18 (0.4 deg until Jan 2024) | 10 d | CC BY 4.0 |
| AIFS Single | ECMWF open data on AWS | 2024-03-01 | 15 d | CC BY 4.0 |
| AIGFS | NOAA S3 (GraphCastGFS until Apr 2026) | 2024-02-05 | 16 d | Public domain |
| GraphCast | NOAA/CIRA archive, GFS initial conditions | 2022-01-01 | 10 d | NOAA output; see note |
| Pangu-Weather | NOAA/CIRA archive | 2020-10-01 | 10 d | NOAA output; weights CC BY-NC-SA 4.0 |
| FourCastNet v2 | NOAA/CIRA archive | 2020-10-01 | 10 d | NOAA output; weights unverified |
| Aurora | NOAA/CIRA archive | 2025-01-01 | 10 d | NOAA output; weights MIT |
| ERA5 | Google ARCO-ERA5 | 1940 | truth | Copernicus licence |
| GFS analysis | NOAA S3 | 2021-01-01 | provisional truth | Public domain |

- IFS before 2023 is not in open data. WeatherBench 2 and TIGGE may hold it; not checked.
- **Licence note for going public.** The repository stores only regional degree-day numbers derived from NOAA's published output files, not model weights. Pangu's weights are non-commercial (checked) and GraphCast's were historically non-commercial; DeepMind's repository now lists non-code materials as CC BY 4.0 (checked). If this ever supports paid work, review those two before relying on their series.
- Earth2Studio weights (checked on Hugging Face): FourCastNet 3 Apache-2.0; AIFS CC BY 4.0; Aurora MIT; Atlas NVIDIA Open Model License; CorrDiff ERA5-HRRR OpenMDW-1.1.

## Storage and budgets

- **Tier 1, in git** (`data/`): regional series as Parquet, one file per init day shared by all models, plus monthly truth files, run manifests (JSONL) and market CSVs. A file per run was tried first and was 11 KB of mostly Parquet overhead; per-day files are about ten times smaller. Only the last few days' files change, so history grows roughly with the data.
- **Tier 2, off git:** daily-mean temperature maps for 00Z runs and for truth, as small compressed files in `.cache/fields/`, bundled per model and month into GitHub Release assets (`wxcc fields publish` / `pull`).
- **Local cache cap:** 3 GB, pruned least-recently-used after every update and pull. Downloads are streamed and cropped in memory; nothing global is written to disk.
- **Measured footprint** after the history backfill: see the table in README.md.
- **Colab:** per-run estimates are in the notebooks; each run records its measured time and estimated units in its manifest.
- **GitHub Actions:** two runs a day at about 5 minutes each, roughly 300 of the 2,000 free minutes a month. Pages deploys only when the repository is public.

## Validation

**1. ERA5 degree days vs NOAA CPC** (station-based, population-weighted by census division; shares no data or code with this pipeline).

| Period | Variable | CONUS ours / CPC | Bias | Daily correlation across divisions |
|---|---|---|---|---|
| Jan 2026 | HDD/day | 27.3 / 29.3 | -6.7% | 0.82 to 0.99 |
| Feb 2021 (Uri) | HDD/day | 26.8 / 28.6 | -6.6% | 0.88 to 1.00 |
| Jul 2026 | CDD/day | 13.5 / 11.9 | +13% | 0.96 to 0.99 |

Day-to-day variation matches closely (Uri's peak day in West South Central: 49.9 vs 49). Our series runs about 1 to 1.5 F warmer than CPC in both seasons.

**2. ERA5 vs 31 big-city airport stations** (`wxcc validate-stations`), as (Tmax+Tmin)/2 at the nearest grid cell.

| Month | ERA5 minus station (mean) | Median |
|---|---|---|
| Jan 2026 | -0.8 F | -0.7 F |
| Jul 2026 | -1.4 F | -1.5 F |

**Conclusion.** ERA5 is slightly *colder* than airports in the largest cities, yet warmer than CPC. So the gap to CPC is not an ERA5 warm bias. It comes from method: CPC averages stations over whole climate divisions, which are cooler than where people actually live, while this pipeline weights the grid cells where people are. The ordering is city airports (warmest), then this pipeline, then CPC. Mountain-division cities (Phoenix, Las Vegas, Salt Lake City) show the largest differences in every comparison, where 25 km cells mix valley floors with terrain.

**What that means in use.** The series is internally consistent and fine for comparing models and for regressions against prices or storage. Its level differs from the CPC and EIA degree days quoted in market reports by roughly 5-10% in winter; do not mix the two without re-basing.

**3. Cross-checks built into the pipeline.** 33 unit tests cover the degree-day maths, day windowing, weighting, the non-linearity of HDD, store idempotency, manifests, and both lab ingest paths. The lab path was run end to end on CPU with Earth2Studio 0.20.0 and its Persistence model.

## Things that are not done or not verified

- **Colab GPU runs.** The notebooks were executed on CPU with a test model only. No GPU model has been run, so memory fit and compute-unit costs are estimates. CorrDiff in particular may not fit a Colab Pro GPU.
- **Scheduled workflow.** Pushed and syntactically valid; its first scheduled run had not happened when this was written.
- **Ensembles** (IFS ENS, AIFS ENS, GEFS): deferred, as the brief allowed.
- **Precipitation and wind maps:** deferred to a later phase, as the brief allowed. The adapters fetch one GRIB field by name, so adding a variable is a small change.
- **ERCOT and PJM prices; Henry Hub futures:** need keys or paid data.
- **Event dates** other than Winter Storm Fern were set from memory and then checked only against the ERA5 series (each window does contain a clear peak). They were not checked against published storm reports.
- **Colab plan details:** Google's FAQ confirms that Pro notebooks run at most 12 hours and that background execution is a higher-plan feature; compute-unit prices and burn rates come from third-party reports.
