"""Degree-day maths. Pure functions on numpy arrays; no I/O.

Conventions (see DECISIONS.md):
- Base temperature 65 F.
- A "day" D runs from D 06:00 UTC to D+1 06:00 UTC, roughly local midnight to
  midnight in the Central time zone.
- Degree days are computed at every grid cell first and averaged afterwards.
  HDD is non-linear in temperature, so HDD of an averaged temperature is not
  the average HDD; the order matters.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

BASE_F = 65.0
DAY_START_HOUR_UTC = 6

# method name -> (sampling step in hours, how samples become a daily temperature)
METHODS = {
    "mean6h": (6, "mean"),  # 06, 12, 18, 00Z: available from every model
    "mean1h": (1, "mean"),  # 24 hourly samples
    "minmax1h": (1, "minmax"),  # (Tmax + Tmin) / 2 from hourly: the NOAA/CPC convention
}


def kelvin_to_f(t_k: np.ndarray) -> np.ndarray:
    return (np.asarray(t_k, dtype=np.float64) - 273.15) * 9.0 / 5.0 + 32.0


def hdd(t_f: np.ndarray, base: float = BASE_F) -> np.ndarray:
    return np.maximum(base - np.asarray(t_f, dtype=np.float64), 0.0)


def cdd(t_f: np.ndarray, base: float = BASE_F) -> np.ndarray:
    return np.maximum(np.asarray(t_f, dtype=np.float64) - base, 0.0)


def required_times(day: pd.Timestamp, method: str) -> pd.DatetimeIndex:
    """UTC sample times needed to compute ``method`` for calendar label ``day``."""
    step, _ = METHODS[method]
    start = pd.Timestamp(day).normalize() + pd.Timedelta(hours=DAY_START_HOUR_UTC)
    if step == 6:
        # 06, 12, 18Z on D and 00Z on D+1
        return pd.date_range(start, periods=4, freq="6h")
    return pd.date_range(start, periods=24, freq="1h")


@dataclass
class DailyTemps:
    """Daily temperature (F) per grid cell for the days that had every sample."""

    days: pd.DatetimeIndex
    t_f: np.ndarray  # (n_days, ...)
    n_samples: int


def daily_temperature(times: pd.DatetimeIndex, t2m_k: np.ndarray, method: str) -> DailyTemps:
    """Collapse sub-daily 2 m temperature (K) to one temperature (F) per day.

    ``times`` are UTC valid times matching the first axis of ``t2m_k``. Days
    missing any required sample are dropped rather than estimated, so a partial
    day at the end of a forecast never produces a biased value.
    """
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}; choose from {sorted(METHODS)}")
    _, how = METHODS[method]
    times = pd.DatetimeIndex(times)
    if times.tz is not None:
        times = times.tz_convert("UTC").tz_localize(None)
    pos = pd.Series(np.arange(times.size), index=times)
    if not pos.index.is_unique:
        raise ValueError("duplicate valid times")

    first = (times.min() - pd.Timedelta(hours=DAY_START_HOUR_UTC)).normalize()
    last = (times.max() - pd.Timedelta(hours=DAY_START_HOUR_UTC)).normalize()
    days, out = [], []
    n = len(required_times(first, method))
    for day in pd.date_range(first, last, freq="D"):
        need = required_times(day, method)
        idx = pos.reindex(need)
        if idx.isna().any():
            continue
        t_f = kelvin_to_f(t2m_k[idx.to_numpy(dtype=int)])
        if how == "mean":
            daily = t_f.mean(axis=0)
        else:
            daily = (t_f.max(axis=0) + t_f.min(axis=0)) / 2.0
        days.append(day)
        out.append(daily)
    shape = (0,) + tuple(np.shape(t2m_k)[1:])
    return DailyTemps(pd.DatetimeIndex(days), np.stack(out) if out else np.empty(shape), n)
