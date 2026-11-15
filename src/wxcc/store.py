"""The regional degree-day store: small Parquet files committed to the repo.

Layout (one schema for every model, analysis or forecast):

    data/regional/<model>/analysis/<YYYY-MM>.parquet     keyed by valid month
    data/regional/<model>/forecast/<YYYY>/<YYYYMMDDHH>.parquet   one per run

Forecast files are written once per run and never rewritten, so git history
grows only by the size of the new data. Analysis files are upserted by key.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from . import __version__
from .regions import REGIONS

ROOT = Path("data/regional")
KEY = ["model", "init_time", "valid_date", "region", "method"]
COLUMNS = [
    "model",  # e.g. era5, gfs, ifs, aifs
    "kind",  # analysis | forecast
    "init_time",  # UTC run time; null for analysis
    "valid_date",  # day label: covers 06Z that day to 06Z the next
    "lead_days",  # valid_date - init date; null for analysis
    "region",  # census division code or CONUS
    "method",  # see degree_days.METHODS
    "hdd",
    "cdd",
    "tmean_f",  # population-weighted daily temperature
    "quality",  # final | prelim (ERA5T) | forecast
    "source",
    "pipeline_version",
]


def make_rows(
    *,
    model: str,
    days: pd.DatetimeIndex,
    regional: dict[str, np.ndarray],
    method: str,
    quality: str | list[str],
    source: str,
    init_time: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Long-format rows from regional arrays shaped (n_days, n_regions)."""
    n_days, n_regions = len(days), len(REGIONS)
    df = pd.DataFrame(
        {
            "valid_date": np.repeat(days.to_numpy(), n_regions),
            "region": np.tile(np.array(REGIONS), n_days),
            "hdd": np.round(regional["hdd"].reshape(-1), 3),
            "cdd": np.round(regional["cdd"].reshape(-1), 3),
            "tmean_f": np.round(regional["tmean_f"].reshape(-1), 3),
        }
    )
    df["model"] = model
    df["kind"] = "analysis" if init_time is None else "forecast"
    df["init_time"] = pd.Timestamp(init_time) if init_time is not None else pd.NaT
    df["init_time"] = df["init_time"].astype("datetime64[ms]")
    df["valid_date"] = df["valid_date"].astype("datetime64[ms]")
    if init_time is None:
        df["lead_days"] = pd.array([pd.NA] * len(df), dtype="Int16")
    else:
        lead = (df["valid_date"] - pd.Timestamp(init_time).normalize()).dt.days
        df["lead_days"] = lead.astype("Int16")
    df["method"] = method
    df["quality"] = np.repeat(np.array(quality), n_regions) if not isinstance(quality, str) else quality
    df["source"] = source
    df["pipeline_version"] = __version__
    return df[COLUMNS]


def _upsert(path: Path, new: pd.DataFrame) -> int:
    """Merge rows into a Parquet file by key; later rows win. Returns rows added or changed."""
    if path.exists():
        old = pd.read_parquet(path)
        merged = pd.concat([old, new], ignore_index=True)
    else:
        old, merged = None, new
    merged = merged.drop_duplicates(KEY, keep="last").sort_values(KEY).reset_index(drop=True)
    if old is not None and len(old) == len(merged) and old[COLUMNS].equals(merged[COLUMNS]):
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    merged[COLUMNS].to_parquet(path, index=False, compression="zstd")
    return len(merged) - (0 if old is None else len(old))


def write_analysis(df: pd.DataFrame, root: Path = ROOT) -> list[Path]:
    paths = []
    for (model, month), part in df.groupby(["model", df["valid_date"].dt.strftime("%Y-%m")]):
        path = root / model / "analysis" / f"{month}.parquet"
        _upsert(path, part)
        paths.append(path)
    return paths


def forecast_path(model: str, init_time: pd.Timestamp, root: Path = ROOT) -> Path:
    t = pd.Timestamp(init_time)
    return root / model / "forecast" / f"{t:%Y}" / f"{t:%Y%m%d%H}.parquet"


def write_forecast(df: pd.DataFrame, root: Path = ROOT) -> Path:
    path = forecast_path(df["model"].iloc[0], df["init_time"].iloc[0], root)
    _upsert(path, df)
    return path


def stored_analysis_days(model: str, method: str, root: Path = ROOT) -> dict[pd.Timestamp, str]:
    """Days already stored for an analysis model -> their quality flag."""
    files = sorted((root / model / "analysis").glob("*.parquet"))
    if not files:
        return {}
    df = pd.concat(pd.read_parquet(f, columns=["valid_date", "method", "quality"]) for f in files)
    df = df[df["method"] == method].drop_duplicates("valid_date")
    return dict(zip(pd.DatetimeIndex(df["valid_date"]), df["quality"]))


def query(
    model: str | None = None,
    region: str | None = None,
    start: str | None = None,
    end: str | None = None,
    init: str | None = None,
    method: str | None = None,
    root: Path = ROOT,
) -> pd.DataFrame:
    """Filter the store. All arguments are optional; dates are inclusive."""
    files = [str(p) for p in root.rglob("*.parquet")]
    if not files:
        return pd.DataFrame(columns=COLUMNS)
    where, params = [], []
    for column, value in (("model", model), ("region", region), ("method", method)):
        if value is not None:
            where.append(f"{column} = ?")
            params.append(value)
    if start is not None:
        where.append("valid_date >= ?")
        params.append(pd.Timestamp(start))
    if end is not None:
        where.append("valid_date <= ?")
        params.append(pd.Timestamp(end))
    if init is not None:
        where.append("init_time = ?")
        params.append(pd.Timestamp(init))
    sql = "SELECT * FROM read_parquet(?, union_by_name=true)"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY model, init_time, valid_date, region, method"
    return duckdb.execute(sql, [files, *params]).df()


def inventory(root: Path = ROOT) -> pd.DataFrame:
    """What is stored: one row per model/kind/method with date range and counts."""
    files = [str(p) for p in root.rglob("*.parquet")]
    if not files:
        return pd.DataFrame()
    sql = """
        SELECT model, kind, method,
               min(valid_date)::DATE AS first_valid, max(valid_date)::DATE AS last_valid,
               count(DISTINCT valid_date) AS valid_days,
               count(DISTINCT init_time) AS runs,
               count(*) AS rows
        FROM read_parquet(?, union_by_name=true)
        GROUP BY ALL ORDER BY ALL
    """
    return duckdb.execute(sql, [files]).df()
