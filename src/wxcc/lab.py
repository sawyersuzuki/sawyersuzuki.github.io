"""Bring forecasts made in the Colab lab into the same store as everything else.

A lab notebook runs a model with Earth2Studio, then hands this module the 2 m
temperature it produced. From there the path is identical to the daily job:
crop to CONUS, compute population-weighted degree days, write the regional
series, a manifest and the daily maps. The dashboard picks the run up on its
next build, shown as "Lab: <model>".
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import fields, pipeline, store, weights
from .sources import grib

PREFIX = "lab_"


def ingest_arrays(
    *,
    model: str,
    init_time: str | pd.Timestamp,
    valid_times,
    t2m_k: np.ndarray,
    lats: np.ndarray,
    lons: np.ndarray,
    config: dict | None = None,
) -> dict:
    """Store one lab forecast.

    ``t2m_k`` is (n_times, n_lat, n_lon) in kelvin on a regular global lat/lon
    grid; ``lats`` may run either way and ``lons`` may be 0..360 or -180..180.
    ``config`` is recorded in the manifest (model version, GPU, runtime, notes).
    """
    model_id = model if model.startswith(PREFIX) else PREFIX + model.lower().replace(" ", "_")
    init = pd.Timestamp(init_time).tz_localize(None) if pd.Timestamp(init_time).tzinfo else pd.Timestamp(init_time)
    times = pd.DatetimeIndex(valid_times)
    t2m_k = np.asarray(t2m_k, dtype=np.float32)
    lats, lons = np.asarray(lats, dtype=float), np.asarray(lons, dtype=float)
    if t2m_k.shape != (len(times), len(lats), len(lons)):
        raise ValueError(f"t2m_k shape {t2m_k.shape} does not match ({len(times)}, {len(lats)}, {len(lons)})")
    if not (150.0 < float(np.nanmean(t2m_k)) < 350.0):
        raise ValueError("t2m_k does not look like kelvin")
    if lats[0] < lats[-1]:  # make north-to-south
        lats, t2m_k = lats[::-1], t2m_k[:, ::-1, :]
    res = float(abs(lats[1] - lats[0]))
    conus = np.stack([grib.to_conus(f, float(lats[0]), float(lons[0]), res) for f in t2m_k])

    w = weights.load()
    days, regional, t_f = pipeline.regional_degree_days(times, conus, pipeline.FORECAST_METHOD, w)
    if not len(days):
        raise ValueError("no complete 06Z-06Z day in this forecast; run at least 30 hours at 6-hourly steps")
    rows = store.make_rows(
        model=model_id, days=days, regional=regional, method=pipeline.FORECAST_METHOD,
        quality="forecast", source="Earth2Studio lab run", init_time=init,
    )
    path = store.write_forecast(rows, lab=True)
    if init.hour == pipeline.FIELD_CYCLE:
        fields.save_forecast(model_id, init, days, t_f)
    manifest = store.write_manifest(
        model=model_id, init_time=init, source="Earth2Studio lab run", method=pipeline.FORECAST_METHOD,
        n_steps=len(times), missing_steps=[], first_valid=days[0], last_valid=days[-1],
        detail=config or {},
    )
    store.flush_manifests()
    return {"model": model_id, "init_time": manifest["init_time"], "days": len(days), "file": str(path),
            "conus_hdd_by_day": [round(float(x), 1) for x in regional["hdd"][:, -1]]}


def curvilinear_weights(lat2d: np.ndarray, lon2d: np.ndarray, tracts: pd.DataFrame | None = None) -> np.ndarray:
    """Population weights for any grid given as 2-D latitude/longitude arrays.

    Each census tract goes to its nearest grid cell (within about 10 km), so
    this works for projected grids such as HRRR's 3 km Lambert grid. Returns a
    (n_regions, H*W) matrix whose rows sum to 1. Needs scipy.
    """
    from scipy.spatial import cKDTree

    from .regions import CONUS, DIVISIONS, EXTRA_REGIONS, REGIONS, STATE_TO_DIVISION

    tracts = weights.fetch_tract_centres() if tracts is None else tracts
    tracts = tracts[tracts["STATEFP"].isin(STATE_TO_DIVISION) & (tracts["POPULATION"] > 0)]
    lat2d, lon2d = np.asarray(lat2d, dtype=float), ((np.asarray(lon2d, dtype=float) + 180.0) % 360.0) - 180.0

    def xyz(lat, lon):
        la, lo = np.radians(lat), np.radians(lon)
        return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])

    tree = cKDTree(xyz(lat2d.ravel(), lon2d.ravel()))
    dist, cell = tree.query(xyz(tracts["LATITUDE"].to_numpy(), tracts["LONGITUDE"].to_numpy()))
    near = dist < 10.0 / 6371.0  # chord length on the unit sphere, about 10 km
    cell, pop = cell[near], tracts["POPULATION"].to_numpy(dtype=float)[near]
    state = tracts["STATEFP"].to_numpy()[near]
    division = np.array([STATE_TO_DIVISION[s] for s in state])
    w = np.zeros((len(REGIONS), lat2d.size))
    for i, region in enumerate(REGIONS):
        if region == CONUS:
            sel = np.ones(len(cell), bool)
        elif region in DIVISIONS:
            sel = division == region
        else:
            sel = np.isin(state, EXTRA_REGIONS[region][1])
        np.add.at(w[i], cell[sel], pop[sel])
        if w[i].sum() > 0:
            w[i] /= w[i].sum()
    return w


def ingest_downscaled(
    *,
    model: str,
    valid_times,
    t2m_k: np.ndarray,
    lat2d: np.ndarray,
    lon2d: np.ndarray,
    config: dict | None = None,
    w: np.ndarray | None = None,
) -> dict:
    """Store degree days from a downscaled analysis (e.g. CorrDiff applied to ERA5).

    ``t2m_k`` is (n_times, H, W) on the grid described by ``lat2d``/``lon2d`` and
    must include the 06, 12, 18 and 00 UTC samples of each day wanted. Rows are
    written as an analysis series under the model id ``lab_<model>``, so they
    can be compared day by day with ERA5 at 0.25 degrees.
    """
    from . import degree_days as dd

    model_id = model if model.startswith(PREFIX) else PREFIX + model.lower().replace(" ", "_")
    times = pd.DatetimeIndex(valid_times)
    t2m_k = np.asarray(t2m_k, dtype=np.float32)
    if t2m_k.shape != (len(times),) + np.shape(lat2d):
        raise ValueError(f"t2m_k shape {t2m_k.shape} does not match times and grid {np.shape(lat2d)}")
    w = curvilinear_weights(lat2d, lon2d) if w is None else w
    daily = dd.daily_temperature(times, t2m_k.reshape(len(times), -1), pipeline.FORECAST_METHOD)
    if not len(daily.days):
        raise ValueError("no complete day: provide 06, 12, 18 and next-day 00 UTC for each day")
    regional = {"hdd": dd.hdd(daily.t_f) @ w.T, "cdd": dd.cdd(daily.t_f) @ w.T, "tmean_f": daily.t_f @ w.T}
    rows = store.make_rows(model=model_id, days=daily.days, regional=regional, method=pipeline.FORECAST_METHOD,
                           quality="lab", source="Earth2Studio lab diagnostic")
    paths = store.write_analysis(rows)
    for day in daily.days:
        store.write_manifest(model=model_id, init_time=day, source="Earth2Studio lab diagnostic",
                             method=pipeline.FORECAST_METHOD, n_steps=4, missing_steps=[],
                             first_valid=day, last_valid=day, detail=config or {})
    store.flush_manifests()
    return {"model": model_id, "days": [f"{d:%Y-%m-%d}" for d in daily.days], "files": [str(p) for p in paths],
            "conus_hdd_by_day": [round(float(x), 1) for x in regional["hdd"][:, -1]]}
