"""Turn gridded 2 m temperature into stored regional degree days."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import degree_days as dd
from . import store, weights
from .sources import era5


def regional_degree_days(
    times: pd.DatetimeIndex, t2m_k: np.ndarray, method: str, w: np.ndarray
) -> tuple[pd.DatetimeIndex, dict[str, np.ndarray]]:
    """Daily population-weighted HDD, CDD and temperature per region."""
    daily = dd.daily_temperature(times, t2m_k, method)
    return daily.days, {
        "hdd": weights.regional_mean(dd.hdd(daily.t_f), w),
        "cdd": weights.regional_mean(dd.cdd(daily.t_f), w),
        "tmean_f": weights.regional_mean(daily.t_f, w),
    }


@dataclass
class Plan:
    """What a backfill will do, computed before anything is downloaded."""

    model: str
    method: str
    days: pd.DatetimeIndex  # days still to fetch
    skipped: int  # days already stored
    unavailable: int  # days not yet published
    chunks: int
    download_mb: float
    est_minutes: float
    stored_kb: float

    def describe(self) -> str:
        if not len(self.days):
            return (
                f"{self.model}/{self.method}: nothing to do "
                f"({self.skipped} days already stored, {self.unavailable} not yet published)."
            )
        return (
            f"{self.model}/{self.method}: {len(self.days)} days to fetch "
            f"({self.days[0]:%Y-%m-%d} to {self.days[-1]:%Y-%m-%d}); "
            f"{self.skipped} already stored, {self.unavailable} not yet published.\n"
            f"  download  ~{self.download_mb:,.0f} MB streamed ({self.chunks:,} hourly fields), "
            f"cropped in memory, nothing cached on disk\n"
            f"  stored    ~{self.stored_kb:,.0f} KB added to the repo\n"
            f"  runtime   ~{self.est_minutes:.1f} min"
        )


def plan_era5(start: str, end: str, method: str, refresh: bool = False) -> Plan:
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
    days = pd.DatetimeIndex(todo)
    per_day = len(dd.required_times(pd.Timestamp("2000-01-01"), method))
    chunks = per_day * len(days)
    return Plan(
        model="era5",
        method=method,
        days=days,
        skipped=len(usable) - len(days),
        unavailable=len(wanted) - len(usable),
        chunks=chunks,
        download_mb=chunks * era5.CHUNK_MB,
        est_minutes=max(chunks * 0.06 / 60, 0.1),  # ~16 parallel fetches at ~1 s each
        stored_kb=len(days) * 0.35,
    )


def run_era5(plan: Plan, batch_days: int = 31, progress=print) -> int:
    """Execute a plan month by month so an interrupted run resumes where it stopped."""
    if not len(plan.days):
        return 0
    w = weights.load()
    avail = era5.availability()
    written = 0
    for i in range(0, len(plan.days), batch_days):
        batch = plan.days[i : i + batch_days]
        times = pd.DatetimeIndex(
            sorted({t for d in batch for t in dd.required_times(d, plan.method)})
        )
        t2m = era5.fetch_t2m(times)
        days, regional = regional_degree_days(times, t2m, plan.method, w)
        quality = ["final" if d < avail.final_through else "prelim" for d in days]
        rows = store.make_rows(
            model="era5",
            days=days,
            regional=regional,
            method=plan.method,
            quality=quality,
            source="ARCO-ERA5 (Google Cloud), Copernicus C3S",
        )
        store.write_analysis(rows)
        written += len(days)
        progress(f"  stored {batch[0]:%Y-%m-%d} to {batch[-1]:%Y-%m-%d} ({written}/{len(plan.days)} days)")
    return written
