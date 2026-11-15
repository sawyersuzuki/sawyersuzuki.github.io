"""Turn gridded 2 m temperature into stored regional degree days.

Two entry points share everything: ``update`` (latest runs, run daily) and
``backfill`` (any date range, on demand). Both plan first, skip what is already
stored, and write the same files.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import degree_days as dd
from . import fields, store, weights
from .models import ANALYSIS_MODELS, FORECAST_MODELS
from .sources import era5, gfs
from .sources.http import NotAvailable

FORECAST_METHOD = "mean6h"  # the one definition every model supports
FIELD_CYCLE = 0  # maps are kept for 00Z runs only, to bound storage
SECONDS_PER_RUN = 5.0
RUN_WORKERS = int(os.environ.get("WXCC_RUN_WORKERS", "4"))
KB_PER_RUN = 2.5
PROVISIONAL_DAYS = 21  # how far back GFS analysis may stand in for missing ERA5


def regional_degree_days(
    times: pd.DatetimeIndex, t2m_k: np.ndarray, method: str, w: np.ndarray
) -> tuple[pd.DatetimeIndex, dict[str, np.ndarray], np.ndarray]:
    """Daily population-weighted HDD, CDD and temperature per region, plus the daily grids (F)."""
    daily = dd.daily_temperature(times, t2m_k, method)
    regional = {
        "hdd": weights.regional_mean(dd.hdd(daily.t_f), w),
        "cdd": weights.regional_mean(dd.cdd(daily.t_f), w),
        "tmean_f": weights.regional_mean(daily.t_f, w),
    }
    return daily.days, regional, daily.t_f


@dataclass
class Plan:
    """What a job will do, computed before anything is downloaded."""

    model: str
    method: str
    items: list  # days (analysis) or init times (forecast) still to fetch
    skipped: int
    unavailable: int
    download_mb: float
    est_minutes: float
    stored_kb: float
    unit: str = "days"
    note: str = ""

    def describe(self) -> str:
        head = f"{self.model}/{self.method}"
        if not self.items:
            return f"{head}: nothing to do ({self.skipped} {self.unit} already stored, {self.unavailable} unavailable)."
        first, last = self.items[0], self.items[-1]
        fmt = "%Y-%m-%d" if self.unit == "days" else "%Y-%m-%d %HZ"
        return (
            f"{head}: {len(self.items)} {self.unit} to fetch ({first.strftime(fmt)} to {last.strftime(fmt)}); "
            f"{self.skipped} already stored, {self.unavailable} unavailable.\n"
            f"  download  ~{self.download_mb:,.0f} MB streamed, cropped to CONUS in memory\n"
            f"  disk      ~{self.stored_kb:,.0f} KB added to the repo"
            + (f"; {self.note}" if self.note else "")
            + f"\n  runtime   ~{self.est_minutes:.1f} min"
        )


# ----------------------------------------------------------------------------- ERA5 truth


def plan_era5(start: str, end: str, method: str = FORECAST_METHOD, refresh: bool = False) -> Plan:
    avail = era5.availability()
    wanted = pd.date_range(start, end, freq="D")
    # A day needs samples up to 06Z the next day, so the last usable label is one day earlier.
    usable = wanted[wanted < avail.prelim_through]
    have = store.stored_analysis_days("era5", method)
    todo = [
        d
        for d in usable
        if refresh
        or d not in have
        # re-fetch preliminary days once the final data has been published
        or (have[d] == "prelim" and d < avail.final_through)
    ]
    per_day = len(dd.required_times(pd.Timestamp("2000-01-01"), method))
    chunks = per_day * len(todo)
    return Plan(
        model="era5", method=method, items=todo,
        skipped=len(usable) - len(todo), unavailable=len(wanted) - len(usable),
        download_mb=chunks * era5.CHUNK_MB,
        est_minutes=max(chunks * 0.06 / 60, 0.1),  # ~16 parallel fetches at ~1 s each
        stored_kb=len(todo) * 0.35,
    )


def run_era5(plan: Plan, batch_days: int = 31, progress=print) -> int:
    """Execute a plan month by month so an interrupted run resumes where it stopped."""
    if not plan.items:
        return 0
    w = weights.load()
    avail = era5.availability()
    all_days = pd.DatetimeIndex(plan.items)
    written = 0
    for i in range(0, len(all_days), batch_days):
        batch = all_days[i : i + batch_days]
        times = pd.DatetimeIndex(sorted({t for d in batch for t in dd.required_times(d, plan.method)}))
        got_times, t2m = era5.fetch_t2m(times)
        if not len(got_times):
            progress(f"  era5: {batch[0]:%Y-%m-%d} to {batch[-1]:%Y-%m-%d} not published yet")
            continue
        days, regional, t_f = regional_degree_days(got_times, t2m, plan.method, w)
        if not len(days):
            continue
        quality = ["final" if d < avail.final_through else "prelim" for d in days]
        rows = store.make_rows(
            model="era5", days=days, regional=regional, method=plan.method, quality=quality,
            source="ARCO-ERA5 (Google Cloud), Copernicus C3S",
        )
        store.write_analysis(rows)
        if plan.method == FORECAST_METHOD:
            fields.save_analysis("era5", days, t_f)
        written += len(days)
        progress(f"  era5: stored {days[0]:%Y-%m-%d} to {days[-1]:%Y-%m-%d} ({written}/{len(all_days)} days)")
    return written


# ----------------------------------------------------------------------------- GFS analysis (provisional truth)


def plan_gfs_analysis(start: str, end: str, refresh: bool = False) -> Plan:
    wanted = pd.date_range(start, end, freq="D")
    latest = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)
    usable = wanted[(wanted <= latest) & (wanted >= ANALYSIS_MODELS["gfs_anl"].first)]
    have = store.stored_analysis_days("gfs_anl", FORECAST_METHOD)
    todo = [d for d in usable if refresh or d not in have]
    return Plan(
        model="gfs_anl", method=FORECAST_METHOD, items=todo,
        skipped=len(usable) - len(todo), unavailable=len(wanted) - len(usable),
        download_mb=len(todo) * 4 * gfs.GFS.mb_per_step,
        est_minutes=max(len(todo) * 0.5 / 60, 0.1), stored_kb=len(todo) * 0.35,
    )


def run_gfs_analysis(plan: Plan, progress=print) -> int:
    if not plan.items:
        return 0
    w = weights.load()
    days_wanted = pd.DatetimeIndex(plan.items)
    times = pd.DatetimeIndex(sorted({t for d in days_wanted for t in dd.required_times(d, FORECAST_METHOD)}))
    got_times, t2m = gfs.fetch_gfs_analysis(times)
    if not len(got_times):
        return 0
    days, regional, t_f = regional_degree_days(got_times, t2m, FORECAST_METHOD, w)
    keep = days.isin(days_wanted)
    if not keep.any():
        return 0
    rows = store.make_rows(
        model="gfs_anl", days=days[keep], regional={k: v[keep] for k, v in regional.items()},
        method=FORECAST_METHOD, quality="provisional", source="NOAA GFS analysis (f000 of each cycle)",
    )
    store.write_analysis(rows)
    fields.save_analysis("gfs_anl", days[keep], t_f[keep])
    progress(f"  gfs_anl: stored {int(keep.sum())} days")
    return int(keep.sum())


# ----------------------------------------------------------------------------- forecasts


def candidate_inits(model_id: str, start: str, end: str, cycles: tuple[int, ...] | None = None) -> list[pd.Timestamp]:
    m = FORECAST_MODELS[model_id]
    cycles = cycles or m.cycles
    days = pd.date_range(pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize(), freq="D")
    inits = [d + pd.Timedelta(hours=h) for d in days for h in sorted(cycles)]
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    return [t for t in inits if m.first <= t <= now]


def plan_forecast(model_id: str, start: str, end: str, cycles: tuple[int, ...] | None = None,
                  refresh: bool = False) -> Plan:
    m = FORECAST_MODELS[model_id]
    wanted = pd.date_range(pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize(), freq="D")
    n_wanted = len(wanted) * len(cycles or m.cycles)
    inits = candidate_inits(model_id, start, end, cycles)
    have = store.stored_runs(model_id, start, end) if not refresh else set()
    todo = [t for t in inits if t not in have]
    mb = sum(m.adapter.est_mb(t) for t in todo)
    n_maps = sum(1 for t in todo if t.hour == FIELD_CYCLE)
    return Plan(
        model=model_id, method=FORECAST_METHOD, items=todo, unit="runs",
        skipped=len(inits) - len(todo), unavailable=n_wanted - len(inits),
        download_mb=mb, est_minutes=max(len(todo) * SECONDS_PER_RUN / RUN_WORKERS / 60, 0.1),
        stored_kb=len(todo) * KB_PER_RUN,
        note=f"~{n_maps * 0.35:,.0f} MB of maps in the local cache (capped at {fields.CACHE_CAP_GB:g} GB)",
    )


@dataclass
class RunReport:
    stored: list[pd.Timestamp] = field(default_factory=list)
    not_published: list[pd.Timestamp] = field(default_factory=list)
    failed: list[tuple[pd.Timestamp, str]] = field(default_factory=list)


def process_run(model_id: str, init: pd.Timestamp, w: np.ndarray) -> int:
    """Fetch one run, compute regional degree days, write series, manifest and maps."""
    m = FORECAST_MODELS[model_id]
    data = m.adapter.fetch(init)
    days, regional, t_f = regional_degree_days(data.times, data.t2m_k, FORECAST_METHOD, w)
    if not len(days):
        raise NotAvailable(f"{model_id} {init}: no complete days")
    rows = store.make_rows(
        model=model_id, days=days, regional=regional, method=FORECAST_METHOD,
        quality="forecast", source=data.source, init_time=init,
    )
    store.write_forecast(rows)
    if init.hour == FIELD_CYCLE:
        fields.save_forecast(model_id, init, days, t_f)
    store.write_manifest(
        model=model_id, init_time=init, source=data.source, method=FORECAST_METHOD,
        n_steps=len(data.times), missing_steps=data.missing_steps,
        first_valid=days[0], last_valid=days[-1], detail=data.detail,
    )
    return len(days)


def run_forecast(plan: Plan, progress=print, workers: int = RUN_WORKERS) -> RunReport:
    report = RunReport()
    if not plan.items:
        return report
    w = weights.load()

    def one(init: pd.Timestamp):
        try:
            process_run(plan.model, init, w)
            return init, "ok", ""
        except NotAvailable as e:
            return init, "missing", str(e)
        except Exception as e:  # keep going: one bad run must not stop a long backfill
            return init, "error", f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for n, (init, status, message) in enumerate(pool.map(one, plan.items), 1):
            if status == "ok":
                report.stored.append(init)
            elif status == "missing":
                report.not_published.append(init)
            else:
                report.failed.append((init, message))
                progress(f"  {plan.model} {init:%Y-%m-%d %HZ} FAILED: {message[:200]}")
            if n % 20 == 0 or n == len(plan.items):
                progress(f"  {plan.model}: {n}/{len(plan.items)} runs processed "
                         f"({len(report.stored)} stored, {len(report.not_published)} not published)")
    store.flush_manifests()
    return report


# ----------------------------------------------------------------------------- daily update


def update(models: tuple[str, ...], days: int = 3, truth_days: int = 45, progress=print) -> dict[str, RunReport]:
    """Fetch the latest runs and refresh truth. Safe to run any number of times a day."""
    today = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    start = (today - pd.Timedelta(days=truth_days)).strftime("%Y-%m-%d")
    progress("Truth:")
    era_plan = plan_era5(start, today.strftime("%Y-%m-%d"))
    run_era5(era_plan, progress=progress)
    era_days = store.stored_analysis_days("era5", FORECAST_METHOD)
    last_era = max(era_days) if era_days else today - pd.Timedelta(days=truth_days)
    # GFS analysis covers every recent day ERA5 lacks: the last week, plus any gaps in ERA5T
    window = pd.date_range(today - pd.Timedelta(days=PROVISIONAL_DAYS), today, freq="D")
    anl_plan = plan_gfs_analysis(window[0].strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d"))
    anl_plan.items = [d for d in anl_plan.items if d not in era_days]
    run_gfs_analysis(anl_plan, progress=progress)
    progress(f"  ERA5 through {last_era:%Y-%m-%d}; GFS analysis fills the days after that")

    reports = {}
    first = (today - pd.Timedelta(days=days - 1)).strftime("%Y-%m-%d")
    progress("Forecasts:")
    for model_id in models:
        plan = plan_forecast(model_id, first, today.strftime("%Y-%m-%d"))
        report = run_forecast(plan, progress=lambda *_: None)
        reports[model_id] = report
        waiting = ", ".join(f"{t:%d %HZ}" for t in report.not_published) or "none"
        progress(f"  {model_id:10s} new runs: {len(report.stored)}; already stored: {plan.skipped}; "
                 f"not yet published: {waiting}"
                 + (f"; FAILED: {len(report.failed)}" if report.failed else ""))
        for init, message in report.failed:
            progress(f"    {init:%Y-%m-%d %HZ}: {message[:200]}")
    removed = fields.prune()
    progress(f"Cache: {fields.cache_size_gb():.2f} GB" + (f" ({removed} old files pruned)" if removed else ""))
    return reports
