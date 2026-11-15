# wx-command-center

A personal command center for comparing weather models over the contiguous US, focused on extreme heat and cold: where models disagree, how forecasts verified, and eventually how that links to gas and power prices.

**Status:** phase 1 of 5 complete (degree-day engine, ERA5 truth, validation). See [DECISIONS.md](DECISIONS.md) for assumptions and trade-offs.

## Setup

```bash
uv venv && uv pip install -e ".[dev]"
```

```bash
.venv/bin/python -m pytest
```

## Commands

```bash
wxcc backfill --model era5 --start 2025-01-01 --end 2025-03-31
```

Prints the download size, repo growth and runtime, then asks before starting. Safe to re-run: stored days are skipped, and preliminary ERA5 days are refreshed once final data exists. Add `--method minmax1h` for the NOAA-style (Tmax+Tmin)/2 definition, `--yes` to skip the prompt.

```bash
wxcc query --model era5 --region WSC --start 2021-02-10 --end 2021-02-20
```

```bash
wxcc inventory
```

```bash
wxcc validate --start 2026-01-01 --end 2026-01-31
```

Compares stored ERA5 degree days with NOAA CPC's station-based values.

```bash
wxcc weights
```

Rebuilds the population weights from Census data (already committed; rarely needed).

## What am I looking at?

- **HDD / CDD:** heating and cooling degree days against a 65 F base. One day at 45 F is 20 HDD. They are a standard proxy for heating (gas) and cooling (power) demand.
- **Population-weighted:** each 25 km grid cell counts in proportion to the people living there, so a cold snap over Chicago moves the number more than one over rural Montana.
- **Regions:** `NE MA ENC WNC SA ESC WSC MTN PAC` are the nine census divisions; `CONUS` is all of them.
- **Day:** 06 UTC to 06 UTC, roughly midnight to midnight Central.
- **method:** `mean6h` (default) averages the four 6-hourly values every model provides; `minmax1h` is (Tmax+Tmin)/2 from hourly data.
- **quality:** `final` ERA5, or `prelim` for the most recent months, which ECMWF may still revise.

## Data and attribution

- ERA5: contains modified Copernicus Climate Change Service information, accessed via Google's ARCO-ERA5.
- Population: US Census Bureau, 2020 Centers of Population.
- Validation: NOAA Climate Prediction Center degree-day statistics (fetched on demand, not stored).

Nothing here needs a paid service or an API key.
