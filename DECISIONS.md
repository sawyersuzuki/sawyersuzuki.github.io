# Decisions

Assumptions, changes to the original brief, and trade-offs. Newest entries at the bottom of each section.

## Changes to the brief

| # | Brief said | What we do instead | Why |
|---|---|---|---|
| 1 | Open archives roll off in days, so every unarchived day is lost | Treat the daily job as a freshness job; rely on backfill for gaps | Checked the buckets on 2026-11-15: ECMWF's AWS mirror (`s3://ecmwf-forecasts`) holds every run since 2023-01-18 and NOAA's GFS bucket since 2021-01-01. Only ECMWF's own portal is short-lived. Retention on AWS is not guaranteed, so we still archive daily. |
| 2 | "dynamical.org forecasts" listed as a model | Treat dynamical.org as a data source for GFS, IFS ENS and AIFS | It re-hosts other centres' models as Zarr; it has no IFS HRES. |
| 3 | AI models come from Earth2Studio on Colab | V1 takes GraphCast, Pangu, FourCastNet v2, Aurora and AIGFS from NOAA/CIRA's public archives; Colab is for models nobody publishes and for custom hindcasts | No GPU needed, and those archives reach back to Oct 2020 (GraphCast from Jan 2022), which covers the historical events. |
| 4 | CorrDiff for CONUS on Colab Pro | Treat as an experiment, gated on a licence check and a measured memory test | Earth2Studio rates `CorrDiffEra5Hrrr` for an 80 GB GPU; Colab Pro does not guarantee one. |
| 5 | HDD only | Store HDD, CDD and population-weighted temperature | Extreme heat is a stated focus; the extra columns are free. |
| 6 | ERA5 as truth | ERA5 as truth, with GFS analysis as flagged provisional truth for the most recent week | ERA5 preliminary data lags about 7 days. |
| 7 | Dashboard on GitHub Pages | Serve locally until the repo is public | Pages needs a public repo on GitHub Free. Actions does work on private repos (about 2,000 Linux minutes a month included). |

## Definitions

- **Base temperature:** 65 F.
- **Day:** label D covers D 06:00 UTC to D+1 06:00 UTC (about midnight to midnight Central). Alternative considered: the 9am Central gas day; deferred to the market-link phase.
- **Daily temperature, default method `mean6h`:** mean of the 06, 12, 18 and 00 UTC values. Chosen because several AI models only output every 6 hours, so this is the one definition every model can share. `minmax1h` ((Tmax+Tmin)/2 from hourly data, the NOAA convention) and `mean1h` are also implemented for comparison.
- **Order of operations:** degree days are computed per grid cell, then population-weighted. HDD of an averaged temperature is not the average HDD.
- **Incomplete days are dropped**, never estimated.
- **Regions:** the 9 census divisions (contiguous states only, so Pacific excludes Alaska and Hawaii) plus CONUS.
- **Population weights:** 2020 Census tract centres of population, each snapped to the nearest 0.25 degree grid point. 8,001 populated cells, 329.3 million people.
- **Grid:** 0.25 degree, 24N to 50N, 125W to 66.5W (105 x 235). Every global model here publishes on this grid, so cropping needs no interpolation.

## Storage

- **Tier 1, in git:** regional daily series as Parquet under `data/regional/`. Forecasts are one immutable file per run; analysis is one file per valid month, upserted by key `(model, init_time, valid_date, region, method)`. Immutable per-run files keep git history from growing faster than the data.
- **Tier 2, off git (phase 4):** daily-mean CONUS fields in a private Hugging Face dataset repo.
- **Local cache:** none needed so far; ERA5 chunks are decoded in memory and cropped. Budget remains 5 GB total, 3 GB cache.
- **Licences of committed data:** Census (public domain); ERA5-derived series (Copernicus licence, redistributable with attribution).

## Validation (phase 1)

ERA5-derived degree days against NOAA CPC's station-based, population-weighted daily values by census division. CPC shares no data or code with this pipeline.

| Period | Variable | CONUS ours / CPC | CONUS bias | Daily correlation (range over divisions) |
|---|---|---|---|---|
| Jan 2026 | HDD/day | 27.3 / 29.3 | -6.7% | 0.82 to 0.99 |
| Feb 2021 (Uri) | HDD/day | 26.8 / 28.6 | -6.6% | 0.88 to 1.00 |
| Jul 2026 | CDD/day | 13.5 / 11.9 | +13% | 0.96 to 0.99 |

- Day-to-day variation matches closely. Uri's peak day in West South Central: 49.9 HDD (ours) vs 49 (CPC).
- There is a consistent offset: our series is about 1 to 1.5 F warmer than CPC in both winter and summer. It is largest in the Mountain division (-10% HDD, +36% CDD) and the Pacific division has the weakest correlation.
- **Not yet explained.** Ruled out: a day-labelling offset (correlation peaks at zero lag) and coastal cells that are mostly sea (under 10% of population in any division; none in Mountain). Leading hypothesis: CPC averages temperature over whole climate divisions, which in the West include high terrain, while we weight the cells where people live. An ERA5 warm bias is the other candidate. To be tested in phase 2 against a station-anchored analysis (URMA) or ASOS stations.
- Consequence: fine for comparing models with each other and against ERA5. Not yet interchangeable with CPC or EIA degree days, which matters for the market link.
- `mean6h` and `minmax1h` differ by under 1% at CONUS level in January 2026, so the 6-hourly definition costs little.

## Open items

- Explain the CPC offset (above).
- IFS forecasts before 2023 are not in open data; check WeatherBench 2 and TIGGE for Uri, the 2021 heat dome and Elliott.
- Weight licences for AI models are unverified (GraphCast and Pangu weights are believed to be non-commercial). Review before making the repo public.
- Colab limits and burn rates came from third-party sources; measure on the first run.
- Historical event dates other than Winter Storm Fern (23-27 Jan 2026) are unverified; define event windows from the ERA5 series.
- ERA5 warm-season months after 2026-06-30 are preliminary (ERA5T) and are re-fetched automatically once final data is published.
